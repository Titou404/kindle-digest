"""Clean node: keep fresh, unique articles with short snippets.

Exact rules only, no LLM: the same input always gives the same output.
Spotting two articles about the same event with different titles is a
judgment call, left to the rank and select nodes.
"""

import re
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from digest.state import Article, DigestState, NodeMetrics

MAX_AGE = timedelta(hours=24)
SNIPPET_MAX = 300  # characters: enough for the rank node to judge, cheap in tokens
TRACKING_PARAMS = ("utm_", "at_")  # e.g. the BBC adds ?at_medium=RSS&at_campaign=...
BARE_URL = re.compile(r"https?://\S+")
NOT_WORD = re.compile(r"[\W_]+")


def normalize_url(url: str) -> str:
    """Drop tracking parameters and the fragment, keep meaningful ones (HN ?id=...)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith(TRACKING_PARAMS)]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ""))


def title_key(title: str) -> str:
    """Same key for titles that differ only by case or punctuation."""
    return NOT_WORD.sub(" ", title.casefold()).strip()


def shorten(text: str, limit: int = SNIPPET_MAX) -> str:
    """Cut at the last whole word before the limit."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def clean_articles(
    articles: list[Article], now: datetime
) -> tuple[list[Article], dict[str, int]]:
    counts = {"articles_in": len(articles), "invalid": 0, "undated": 0, "too_old": 0, "duplicates": 0}
    kept, seen_urls, seen_titles = [], set(), set()

    for article in articles:
        if not article.title or not article.url:
            counts["invalid"] += 1
            continue
        if article.published is None:
            counts["undated"] += 1
            continue
        if now - article.published > MAX_AGE:
            counts["too_old"] += 1
            continue
        url = normalize_url(article.url)
        key = title_key(article.title)
        if url in seen_urls or (key and key in seen_titles):
            counts["duplicates"] += 1
            continue
        seen_urls.add(url)
        seen_titles.add(key)
        snippet = shorten(" ".join(BARE_URL.sub(" ", article.snippet).split()))
        # New Article objects: "collected" stays untouched, so we can compare before/after.
        kept.append(replace(article, url=url, snippet=snippet))

    counts["articles_out"] = len(kept)
    return kept, counts


def clean(state: DigestState) -> dict:
    start = time.perf_counter()
    kept, counts = clean_articles(state["collected"], now=datetime.now(UTC))
    metrics = NodeMetrics("clean", round(time.perf_counter() - start, 3), counts)
    return {"cleaned": kept, "metrics": [metrics]}
