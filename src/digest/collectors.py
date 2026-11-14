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
# Reddit appends this line to every post in its feeds (split by a <br> in the HTML).
REDDIT_FOOTER = re.compile(r"\s*submitted by\s+/u/\S+\s+to\s+r/\S+\s+\[link\]\s+\[comments\]\s*$")
BLOCK_END = re.compile(r"</(?:p|div|li|h[1-6]|blockquote|pre)>|<br\s*/?>", re.IGNORECASE)


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=10.0,
        follow_redirects=True,
    )


def describe_error(e: Exception) -> str:
    """Short label for an error, e.g. "HTTP 429" or "ConnectTimeout"."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def clean_html(text: str) -> str:
    """Strip tags, decode entities (&amp; ...) and collapse whitespace."""
    return " ".join(html.unescape(TAG.sub(" ", text)).split())


def html_to_text(raw_html: str) -> str:
    """Like clean_html, but keeps the paragraphs, separated by a blank line."""
    paragraphs = (clean_html(part) for part in BLOCK_END.sub("\n\n", raw_html).split("\n\n"))
    return "\n\n".join(p for p in paragraphs if p)


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
    # An HTML page (anti-bot, error) served with status 200 is not a feed: feedparser
    # recognizes no format (empty version) but reports no error either. Fail loudly
    # rather than return an empty list that looks like a quiet day.
    if not feed.version:
        raise ValueError("response is not an RSS/Atom feed")
    return [
        Article(
            source=source.name,
            section=source.section,
            title=clean_html(entry.get("title", "")),
            url=entry.get("link", ""),
            published=_entry_date(entry),
            snippet=REDDIT_FOOTER.sub("", clean_html(entry.get("summary", ""))),
            # Some feeds (Reddit, The Conversation) include the full text:
            # no need to download the page later. Paragraphs are kept.
            text=REDDIT_FOOTER.sub("", html_to_text(entry.content[0].value))
            if entry.get("content")
            else "",
            raw=source.raw,
        )
        for entry in feed.entries
    ]


def _entry_date(entry) -> datetime | None:
    # feedparser gives dates as UTC time.struct_time; Atom feeds may only have "updated".
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*parsed[:6], tzinfo=UTC) if parsed else None


# Which function fetches each kind of source (see "kind" in config/sources.toml).
FETCHERS = {"hn": fetch_hn, "feed": fetch_feed}
