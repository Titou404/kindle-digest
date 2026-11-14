"""Fetch candidate articles from each kind of source.

Plain functions, independent of LangGraph: errors are raised, and the caller
(probe script or graph node) decides how to record them.
"""

import html
import re
from datetime import UTC, datetime

import feedparser
import httpx

from digest.sources import Source
from digest.state import Article

USER_AGENT = "kindle-digest/0.1 (personal project)"
TAG = re.compile(r"<[^>]+>")


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=10.0,
        follow_redirects=True,
    )


def clean_html(text: str) -> str:
    """Strip tags, decode entities (&amp; ...) and collapse whitespace."""
    return " ".join(html.unescape(TAG.sub(" ", text)).split())


def fetch_hn(client: httpx.Client, source: Source) -> list[Article]:
    response = client.get(source.url)
    response.raise_for_status()
    articles = []
    for hit in response.json()["hits"]:
        # "Ask HN" posts have no external link: point to the discussion instead.
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        articles.append(
            Article(
                source=source.name,
                section=source.section,
                title=clean_html(hit["title"]),
                url=url,
                published=datetime.fromtimestamp(hit["created_at_i"], tz=UTC),
                snippet=clean_html(hit.get("story_text") or ""),
            )
        )
    return articles


def fetch_feed(client: httpx.Client, source: Source) -> list[Article]:
    response = client.get(source.url)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    # An HTML page (anti-bot, error) served with status 200 is not a feed:
    # fail loudly rather than return an empty list that looks like a quiet day.
    if feed.bozo and not feed.entries:
        raise ValueError(f"not a valid feed: {feed.bozo_exception}")
    return [
        Article(
            source=source.name,
            section=source.section,
            title=clean_html(entry.get("title", "")),
            url=entry.get("link", ""),
            published=_entry_date(entry),
            snippet=clean_html(entry.get("summary", "")),
        )
        for entry in feed.entries
    ]


def _entry_date(entry) -> datetime | None:
    # feedparser gives dates as UTC time.struct_time; Atom feeds may only have "updated".
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*parsed[:6], tzinfo=UTC) if parsed else None


# Which function fetches each kind of source (see "kind" in config/sources.toml).
FETCHERS = {"hn": fetch_hn, "feed": fetch_feed}
