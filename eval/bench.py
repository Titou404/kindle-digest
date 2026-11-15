"""Evaluation bench: replay rank and summarize on a frozen day, one config at a time.

The frozen day (eval/fixtures/) gives every config exactly the same articles, so any
difference in cost, latency or output comes from the config, not from the news.
The bench calls the production code (rank, select_articles, summarize) through llm.py:
what it measures is what production would do.
"""

import json
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from digest.llm import LLM, LLMOutputError
from digest.nodes.clean import shorten
from digest.nodes.rank import MAX_TOKENS as RANK_MAX_TOKENS
from digest.nodes.rank import PROMPT_VERSION as RANK_PROMPT
from digest.nodes.rank import SCHEMA as RANK_SCHEMA
from digest.nodes.rank import (
    apply_scores,
    build_system_prompt,
    build_user_message,
    fake_scores,
    rank,
)
from digest.nodes.select import select_articles
from digest.nodes.summarize import summarize
from digest.paths import ROOT
from digest.state import Article, LLMCall, SourceError

EVAL_DIR = ROOT / "eval"
CONFIGS_PATH = EVAL_DIR / "configs.toml"
FIXTURES_DIR = EVAL_DIR / "fixtures"  # frozen days: ignored by git (press articles)
RESULTS_DIR = EVAL_DIR / "results"  # real runs: versioned, they feed the evaluation page
FAKE_DIR = ROOT / "out" / "bench"  # --fake runs: ignored by git
PER_ARTICLE_WORKERS = 8  # parallel calls in per-article ranking: gentle on rate limits


@dataclass(frozen=True)
class Config:
    id: str  # "S1", "R1"...
    task: str  # "summarize" or "rank"
    question: str  # what this config is meant to answer
    model: str
    effort: str
    repeats: int
    prompt: str = "v1"  # summarize only: prompts/summarize_<prompt>.md
    max_text: int = 20000  # summarize only: characters of article text sent to the model
    mode: str = "batched"  # rank only: "batched" (one call) or "per_article"


def load_configs(path: Path = CONFIGS_PATH) -> list[Config]:
    with path.open("rb") as f:
        configs = [Config(**entry) for entry in tomllib.load(f)["configs"]]
    ids = [c.id for c in configs]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate config ids: {duplicates}")
    for c in configs:
        if c.task not in {"summarize", "rank"} or c.mode not in {"batched", "per_article"}:
            raise ValueError(f"{c.id}: unknown task {c.task!r} or mode {c.mode!r}")
    return configs


# ---------- Frozen day: JSON file with the candidates and the articles to summarize ----------

def article_to_dict(article: Article) -> dict:
    data = asdict(article)
    data["published"] = article.published.isoformat() if article.published else None
    return data


def article_from_dict(data: dict) -> Article:
    published = datetime.fromisoformat(data["published"]) if data["published"] else None
    return Article(**{**data, "published": published})


def save_fixture(path: Path, candidates: list[Article], articles: list[Article], meta: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "meta": meta,
        "candidates": [article_to_dict(a) for a in candidates],  # input of rank
        "articles": [article_to_dict(a) for a in articles],  # input of summarize, full text
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def load_fixture(path: Path) -> tuple[list[Article], list[Article], dict]:
    data = json.loads(path.read_text())
    candidates = [article_from_dict(a) for a in data["candidates"]]
    articles = [article_from_dict(a) for a in data["articles"]]
    return candidates, articles, data["meta"]


# ---------- Running one config ----------

def run_summarize(config: Config, articles: list[Article], llm: LLM) -> dict:
    def one(article: Article) -> dict:
        # E2: cut the text as fetch_text did before 2026-11-14 (at the last whole word).
        if len(article.text) > config.max_text:
            article = replace(article, text=shorten(article.text, config.max_text))
        return summarize({"article": article}, llm, prompt_version=config.prompt)

    # In parallel, as in production (one Send per article).
    with ThreadPoolExecutor(max_workers=max(len(articles), 1)) as pool:
        outputs = list(pool.map(one, articles))
    items = [
        {"url": a.url, "source": a.source, "title": a.title, "input_chars": len(a.text),
         "summary": a.summary, "why_it_matters": a.why_it_matters,
         "words": len(a.summary.split())}
        for a in (out["summarized"][0] for out in outputs)
    ]
    return {
        "items": items,
        "llm_calls": [c for out in outputs for c in out["llm_calls"]],
        "errors": [e for out in outputs for e in out["errors"]],
    }


def rank_per_article(
    candidates: list[Article], llm: LLM
) -> tuple[list[Article], list[LLMCall], list[SourceError]]:
    """E4: one call per candidate. Same prompt, but each article is judged alone:
    the model can no longer give the same topic to two articles about one event."""
    system = build_system_prompt()

    def one(article: Article) -> tuple[Article, list[LLMCall], list[SourceError]]:
        # Broad except, as in rank: a failed call leaves this article at 0, the rest goes on.
        try:
            data, call = llm.complete_json(
                task="rank",
                prompt_version=RANK_PROMPT,
                system=system,
                user=build_user_message([article]),
                schema=RANK_SCHEMA,
                max_tokens=RANK_MAX_TOKENS,
                # Fake topics must differ per article, or select would see a single event.
                fake_output=lambda: {"scores": [
                    {**fake_scores([article])["scores"][0], "topic": article.title}
                ]},
            )
        except LLMOutputError as e:
            return replace(article, score=0), [e.call], [SourceError("rank", str(e))]
        except Exception as e:  # noqa: BLE001
            return replace(article, score=0), [], [SourceError("rank", type(e).__name__)]
        [scored], _ = apply_scores([article], data["scores"])
        return scored, [call], []

    with ThreadPoolExecutor(max_workers=PER_ARTICLE_WORKERS) as pool:
        outputs = list(pool.map(one, candidates))
    ranked = [article for article, _, _ in outputs]
    calls = [c for _, cs, _ in outputs for c in cs]
    errors = [e for _, _, es in outputs for e in es]
    return ranked, calls, errors


def run_rank(config: Config, candidates: list[Article], llm: LLM) -> dict:
    if config.mode == "batched":
        out = rank({"cleaned": candidates}, llm)
        ranked, calls, errors = out["ranked"], out["llm_calls"], out["errors"]
    else:
        ranked, calls, errors = rank_per_article(candidates, llm)
    # Same selection rules as production: what would have made it into the journal.
    selected, _ = select_articles(ranked)
    selected_urls = {a.url for a in selected}
    items = [
        {"url": a.url, "source": a.source, "section": a.section, "title": a.title,
         "score": a.score, "topic": a.topic, "selected": a.url in selected_urls}
        for a in ranked
    ]
    return {"items": items, "llm_calls": calls, "errors": errors}


def run_config(
    config: Config, candidates: list[Article], articles: list[Article], llm: LLM
) -> dict:
    start = time.perf_counter()
    if config.task == "rank":
        out = run_rank(config, candidates, llm)
    else:
        out = run_summarize(config, articles, llm)
    seconds = time.perf_counter() - start
    calls = out["llm_calls"]
    return {
        "config": asdict(config),
        "totals": {
            "seconds": round(seconds, 2),  # wall time; calls run in parallel
            "llm_calls": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "thinking_tokens": sum(c.thinking_tokens for c in calls),
            "cost_usd": round(sum(c.cost_usd for c in calls), 6),
            "mean_latency_s": round(sum(c.latency_s for c in calls) / len(calls), 3)
            if calls else None,
        },
        "llm_calls": [asdict(c) for c in calls],
        "errors": [asdict(e) for e in out["errors"]],
        "items": out["items"],
    }
