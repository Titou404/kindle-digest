"""Tests for the clean node's rules."""

from datetime import UTC, datetime, timedelta

from digest.nodes.clean import clean_articles
from digest.state import Article

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)


def article(title="A title", url="https://example.com/a", hours_ago=1.0, snippet=""):
    published = NOW - timedelta(hours=hours_ago) if hours_ago is not None else None
    return Article("source", "data", title, url, published=published, snippet=snippet)


def test_keeps_only_dated_articles_from_the_last_24_hours():
    articles = [
        article("Fresh", "https://example.com/1", hours_ago=23),
        article("Too old", "https://example.com/2", hours_ago=25),
        article("No date", "https://example.com/3", hours_ago=None),
    ]

    kept, counts = clean_articles(articles, NOW)

    assert [a.title for a in kept] == ["Fresh"]
    assert counts["too_old"] == 1
    assert counts["undated"] == 1


def test_same_url_with_different_tracking_parameters_is_a_duplicate():
    # Real case: the BBC adds a different at_campaign to the same article in each feed.
    base = "https://www.bbc.co.uk/news/articles/cqx2wyvyr3zzo"
    articles = [
        article("Title in World", f"{base}?at_medium=RSS&at_campaign=world"),
        article("Updated title in Business", f"{base}?at_medium=RSS&at_campaign=business"),
    ]

    kept, counts = clean_articles(articles, NOW)

    assert [a.url for a in kept] == [base]
    assert counts["duplicates"] == 1


def test_meaningful_query_parameters_are_kept():
    # Two different "Ask HN" posts: dropping the whole query would merge them.
    articles = [
        article("Ask HN: first", "https://news.ycombinator.com/item?id=1"),
        article("Ask HN: second", "https://news.ycombinator.com/item?id=2"),
    ]

    kept, _ = clean_articles(articles, NOW)

    assert len(kept) == 2


def test_same_title_ignoring_case_and_punctuation_is_a_duplicate():
    articles = [
        article("La BCE maintient ses taux", "https://example.com/1"),
        article("la BCE maintient ses taux !", "https://example.com/2"),
    ]

    kept, counts = clean_articles(articles, NOW)

    assert len(kept) == 1
    assert counts["duplicates"] == 1


def test_snippet_loses_bare_urls_and_is_cut_on_a_word():
    articles = [
        article("Only links", "https://example.com/1", snippet="https://a.example/x https://b.example/y"),
        article("Long", "https://example.com/2", snippet="word " * 200),
    ]

    kept, _ = clean_articles(articles, NOW)

    assert kept[0].snippet == ""
    long_snippet = kept[1].snippet
    assert len(long_snippet) <= 301
    assert long_snippet.endswith("word…")


def test_input_articles_are_not_modified():
    original = article(url="https://example.com/a?utm_source=rss")

    clean_articles([original], NOW)

    assert original.url == "https://example.com/a?utm_source=rss"
