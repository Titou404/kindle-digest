"""Tests for the fetch_text node, without network."""

import httpx
import pytest

from digest.nodes import fetch_text as fetch_text_module
from digest.nodes.fetch_text import MAX_TEXT, fetch_text
from digest.state import Article

PAGES = {
    "https://ok.example": "word " * 400,  # 2,000 characters: kept as is
    "https://long.example": "word " * 5000,  # 25,000 characters: cut
    "https://video.example": "Watch on YouTube",  # not an article
}


def fake_extract_text(client, url):
    if url == "https://down.example":
        raise httpx.ConnectTimeout("timed out")
    return PAGES[url]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(fetch_text_module, "extract_text", fake_extract_text)


def article(url, text="", raw=False):
    return Article("source", "data", "A title", url, snippet="A snippet", text=text, raw=raw)


def test_raw_post_is_left_as_written():
    long_post = "paragraph\n\n" * 1000  # longer than MAX_TEXT, but not cut

    result = fetch_text({"selected": [article("https://unknown.example", long_post, raw=True)]})

    assert result["selected"][0].text == long_post
    assert result["metrics"][0].counts["raw"] == 1


def test_text_already_in_the_feed_is_not_downloaded():
    # This URL is unknown to fake_extract_text: downloading it would fail the test.
    result = fetch_text({"selected": [article("https://unknown.example", text="x" * 1000)]})

    assert result["selected"][0].text == "x" * 1000
    assert result["metrics"][0].counts["from_feed"] == 1


def test_every_case_is_handled_and_counted():
    urls = ["https://ok.example", "https://long.example", "https://video.example",
            "https://down.example"]

    result = fetch_text({"selected": [article(url) for url in urls]})

    ok, long, video, down = [a.text for a in result["selected"]]
    assert ok == PAGES["https://ok.example"]
    assert len(long) <= MAX_TEXT + 1 and long.endswith("…")
    assert video == ""  # too short: summarize will use the snippet
    assert down == ""
    assert result["errors"][0].error == "ConnectTimeout"
    counts = result["metrics"][0].counts
    assert {k: counts[k] for k in ("from_feed", "downloaded", "failed", "too_short", "truncated")} == {
        "from_feed": 0, "downloaded": 3, "failed": 1, "too_short": 1, "truncated": 1,
    }
    assert counts["chars_kept"] == len(ok) + len(long)
    assert counts["chars_cut"] == 25000 - len(long)  # what the cut removed is measured
