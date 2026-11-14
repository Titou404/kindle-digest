"""Tests for the collectors, without network.

Fixtures are real responses captured on 2026-11-14, trimmed to 2 items.
httpx.MockTransport serves them in place of the real sites.
"""

import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest

from digest.collectors import clean_html, fetch_feed, fetch_hn
from digest.sources import Source

FIXTURES = Path(__file__).parent / "fixtures"
HN = Source("hackernews", "hn", "data", "https://hn.example/api")
BBC = Source("bbc/world", "feed", "monde", "https://bbc.example/rss")
REDDIT = Source("reddit", "feed", "data", "https://reddit.example/rss")


def client_returning(body: bytes, status: int = 200) -> httpx.Client:
    """A client that answers every request with this body, without network."""
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    return httpx.Client(transport=transport)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_clean_html():
    assert clean_html("<p>Tom &amp; Jerry\xa0 </p>\n<br>") == "Tom & Jerry"


def test_fetch_hn():
    articles = fetch_hn(client_returning(fixture("hn.json")), HN)

    assert len(articles) == 2
    first = articles[0]
    assert (first.source, first.section) == ("hackernews", "data")
    assert first.title == "FAA issues national ground stop – lifted 4.5 hours later"
    assert first.url.startswith("https://www.nbcnews.com/")
    assert first.published.tzinfo == UTC


def test_fetch_hn_without_url_links_to_discussion():
    data = json.loads(fixture("hn.json"))
    del data["hits"][0]["url"]  # what an "Ask HN" post looks like

    articles = fetch_hn(client_returning(json.dumps(data).encode()), HN)

    assert articles[0].url == "https://news.ycombinator.com/item?id=50489641"


def test_fetch_feed_rss():
    articles = fetch_feed(client_returning(fixture("bbc.rss")), BBC)

    assert len(articles) == 2
    for article in articles:
        assert article.title and article.snippet
        assert article.url.startswith("https://www.bbc.co")
        assert article.published.tzinfo == UTC
        assert article.text == ""  # the BBC feed has no full text


def test_fetch_feed_reddit_uses_full_text_without_footer():
    articles = fetch_feed(client_returning(fixture("reddit.atom")), REDDIT)

    assert len(articles) == 2
    for article in articles:
        assert article.text
        assert "submitted by" not in article.text
        assert "submitted by" not in article.snippet


def test_fetch_feed_rejects_html_page():
    page = b"<html><head><title>Access denied</title></head><body>Blocked</body></html>"

    with pytest.raises(ValueError, match="not an RSS/Atom feed"):
        fetch_feed(client_returning(page), BBC)


def test_http_error_is_raised():
    with pytest.raises(httpx.HTTPStatusError):
        fetch_feed(client_returning(b"", status=429), REDDIT)
