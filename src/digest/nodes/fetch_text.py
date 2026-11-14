"""Fetch-text node: get the full text of the selected articles only.

We read in full only what we summarize: 12 downloads instead of 120, and fewer tokens.
"""

import time
from dataclasses import replace

from digest.collectors import describe_error, make_client
from digest.extract import extract_text
from digest.nodes.clean import shorten
from digest.state import DigestState, NodeMetrics, SourceError

# Characters (~5,000 tokens). Was 6,000 until 2026-11-14: it cut 7 articles out of 12, so
# summaries described the start of an article and missed its conclusion. No article measured
# so far reaches 20,000; the limit only guards against a broken page. Experiment E2 compares.
MAX_TEXT = 20000
MIN_TEXT = 500  # below this, it is not an article (video page, paywall teaser...)


def fetch_text(state: DigestState) -> dict:
    start = time.perf_counter()
    counts = {"from_feed": 0, "downloaded": 0, "failed": 0, "too_short": 0, "truncated": 0,
              "raw": 0, "chars_kept": 0, "chars_cut": 0}
    articles, errors = [], []

    with make_client() as client:
        for article in state["selected"]:
            if article.raw:  # shown as written: no download, no cut, no summary
                counts["raw"] += 1
                articles.append(article)
                continue
            text = article.text  # Reddit and The Conversation give it in the feed
            if text:
                counts["from_feed"] += 1
            else:
                # Broad except on purpose: one unreadable page must not stop the others.
                try:
                    text = extract_text(client, article.url)
                    counts["downloaded"] += 1
                except Exception as e:  # noqa: BLE001
                    counts["failed"] += 1
                    errors.append(SourceError(f"fetch_text:{article.source}", describe_error(e)))
                    text = ""
            if text and len(text) < MIN_TEXT:
                counts["too_short"] += 1
                text = ""  # summarize will fall back to the snippet
            if len(text) > MAX_TEXT:
                counts["truncated"] += 1
                original_length = len(text)
                text = shorten(text, MAX_TEXT)
                counts["chars_cut"] += original_length - len(text)
            counts["chars_kept"] += len(text)
            articles.append(replace(article, text=text))

    metrics = NodeMetrics("fetch_text", round(time.perf_counter() - start, 3), counts)
    return {"selected": articles, "errors": errors, "metrics": [metrics]}
