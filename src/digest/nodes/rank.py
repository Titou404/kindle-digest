"""Rank node: one batched LLM call scores every candidate for the reader's profile.

"Is this interesting for this reader?" is a judgment, hence an LLM. One call for all
candidates: the instructions and the profile are sent once, not once per article.
"""

import html
import time
import zlib
from dataclasses import replace

from digest.llm import LLM, LLMOutputError
from digest.paths import CONFIG_DIR, PROMPTS_DIR
from digest.state import Article, DigestState, NodeMetrics, SourceError

PROMPT_VERSION = "v1"
MAX_TOKENS = 16000  # ~25 output tokens per article: room for hundreds, plus thinking
SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer"},
                    "topic": {"type": "string"},
                },
                "required": ["id", "score", "topic"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}


def build_system_prompt() -> str:
    prompt = (PROMPTS_DIR / f"rank_{PROMPT_VERSION}.md").read_text()
    profile = (CONFIG_DIR / "profile.md").read_text()
    return prompt.replace("{profil}", profile.strip())


def build_user_message(articles: list[Article]) -> str:
    # Article text is untrusted: escaping < and > stops it from closing or faking our tags.
    lines = ["<articles>"]
    for i, article in enumerate(articles):
        lines.append(f'<article id="{i}" rubrique="{article.section}" source="{article.source}">')
        lines.append(f"Titre : {html.escape(article.title, quote=False)}")
        if article.snippet:
            lines.append(f"Chapô : {html.escape(article.snippet, quote=False)}")
        lines.append("</article>")
    lines.append("</articles>")
    return "\n".join(lines)


def apply_scores(
    articles: list[Article], scores: list[dict]
) -> tuple[list[Article], dict[str, int]]:
    """Attach each score to its article. Missing or invalid scores count as 0."""
    found, invalid = {}, 0
    for entry in scores:
        i, score = entry["id"], entry["score"]
        if not (0 <= i < len(articles) and 0 <= score <= 10):
            invalid += 1
            continue
        found.setdefault(i, entry)  # an id given twice: keep the first one
    ranked = [
        replace(article, score=found[i]["score"], topic=found[i]["topic"])
        if i in found
        else replace(article, score=0)
        for i, article in enumerate(articles)
    ]
    counts = {"scored": len(found), "missing": len(articles) - len(found), "invalid": invalid}
    return ranked, counts


def fake_scores(articles: list[Article]) -> dict:
    # --fake mode: deterministic pseudo-scores (same title, same score, on every run).
    return {"scores": [
        {"id": i, "score": zlib.crc32(article.title.encode()) % 11, "topic": f"fake topic {i}"}
        for i, article in enumerate(articles)
    ]}


def rank(state: DigestState, llm: LLM) -> dict:
    start = time.perf_counter()
    articles = state["cleaned"]
    scores, calls, errors = [], [], []

    if articles:
        # Broad except on purpose: if ranking fails, the journal still goes out
        # (every score stays at 0, so select falls back to the most recent articles).
        try:
            data, call = llm.complete_json(
                task="rank",
                prompt_version=PROMPT_VERSION,
                system=build_system_prompt(),
                user=build_user_message(articles),
                schema=SCHEMA,
                max_tokens=MAX_TOKENS,
                fake_output=lambda: fake_scores(articles),
            )
            calls.append(call)
            scores = data["scores"]
        except LLMOutputError as e:
            calls.append(e.call)  # unusable answer, but billed: it must count in the cost
            errors.append(SourceError(source="rank", error=str(e)))
        except Exception as e:  # noqa: BLE001
            errors.append(SourceError(source="rank", error=type(e).__name__))

    ranked, counts = apply_scores(articles, scores)
    metrics = NodeMetrics(
        "rank", round(time.perf_counter() - start, 3), {"articles_in": len(articles), **counts}
    )
    return {"ranked": ranked, "llm_calls": calls, "errors": errors, "metrics": [metrics]}
