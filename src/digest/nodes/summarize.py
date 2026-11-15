"""Summarize node: one LLM call per selected article, run in parallel (see Send in graph.py).

Summarizing and translating is a language task, hence an LLM. One call per article:
a failure only affects that article, and the total latency is that of the slowest call.
"""

import html
import time
from dataclasses import replace
from typing import TypedDict

from digest.llm import LLM, LLMOutputError
from digest.paths import PROMPTS_DIR
from digest.state import Article, NodeMetrics, SourceError

# v2 since 2026-11-15: in the evaluation bench (eval/), 2 unsupported claims in 12 summaries
# instead of 6 to 7 with v1, no padding on short articles, no outside fact; same cost.
PROMPT_VERSION = "v2"
MAX_TOKENS = 4000  # ~250 tokens of answer, the rest is room for thinking
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "why_it_matters": {"type": "string"},
    },
    "required": ["summary", "why_it_matters"],
    "additionalProperties": False,
}


class SummarizeInput(TypedDict):
    article: Article


def build_user_message(article: Article) -> str:
    # Untrusted text: escaping < > & stops it from closing or faking our tags.
    return (
        f'<article source="{article.source}">\n'
        f"Titre : {html.escape(article.title, quote=False)}\n\n"
        f"{html.escape(article.text, quote=False)}\n"
        "</article>"
    )


def fake_summary(article: Article) -> dict:
    return {
        "summary": f"[Résumé factice] {article.text[:300]}",
        "why_it_matters": "[Factice] Pourquoi c'est important.",
    }


def summarize(state: SummarizeInput, llm: LLM, prompt_version: str = PROMPT_VERSION) -> dict:
    # prompt_version: production uses PROMPT_VERSION; the evaluation bench compares versions.
    start = time.perf_counter()
    article = state["article"]
    calls, errors = [], []

    # No text (unreadable page): no call, the journal shows the snippet. Nothing to invent.
    if article.text:
        # Broad except on purpose: a failed summary must not take the others down.
        try:
            data, call = llm.complete_json(
                task="summarize",
                prompt_version=prompt_version,
                system=(PROMPTS_DIR / f"summarize_{prompt_version}.md").read_text(),
                user=build_user_message(article),
                schema=SCHEMA,
                max_tokens=MAX_TOKENS,
                fake_output=lambda: fake_summary(article),
            )
            calls.append(call)
            article = replace(
                article, summary=data["summary"], why_it_matters=data["why_it_matters"]
            )
        except LLMOutputError as e:
            calls.append(e.call)  # billed, so counted
            errors.append(SourceError(f"summarize:{article.source}", str(e)))
        except Exception as e:  # noqa: BLE001
            errors.append(SourceError(f"summarize:{article.source}", type(e).__name__))

    metrics = NodeMetrics(
        f"summarize:{article.source}",
        round(time.perf_counter() - start, 3),
        {"input_chars": len(article.text), "summary_words": len(article.summary.split())},
    )
    return {"summarized": [article], "llm_calls": calls, "errors": errors, "metrics": [metrics]}
