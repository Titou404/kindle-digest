"""Fetch-text node: get the full text of the selected articles only.

We read in full only what we summarize: 12 downloads instead of 120, and fewer tokens.
"""

import time
from dataclasses import replace

from digest.collectors import describe_error, make_client
from digest.extract import extract_text
from digest.nodes.clean import shorten
from digest.state import DigestState, NodeMetrics, SourceError

MAX_TEXT = 6000  # characters (~1,500 tokens): bounds the cost of each summary (experiment E2)
MIN_TEXT = 500  # below this, it is not an article (video page, paywall teaser...)


def fetch_text(state: DigestState) -> dict:
    start = time.perf_counter()
    counts = {"from_feed": 0, "downloaded": 0, "failed": 0, "too_short": 0, "truncated": 0}
    articles, errors = [], []

    with make_client() as client:
        for article in state["selected"]:
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
                text = shorten(text, MAX_TEXT)
            articles.append(replace(article, text=text))

    metrics = NodeMetrics("fetch_text", round(time.perf_counter() - start, 3), counts)
    return {"selected": articles, "errors": errors, "metrics": [metrics]}
