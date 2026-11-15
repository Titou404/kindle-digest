"""Tests for the collect node and the collection graph, without network."""

from datetime import UTC, datetime

import httpx
import pytest

from digest.collectors import FETCHERS
from digest.graph import build_graph
from digest.llm import FakeLLM
from digest.nodes.collect import collect
from digest.sources import Source
from digest.state import Article, SourceError

OK = Source("ok-source", "feed", "data", "https://ok.example/rss")
BROKEN = Source("broken-source", "feed", "monde", "https://broken.example/rss")


def fake_fetch(client, source):
    if source == BROKEN:
        raise httpx.ConnectTimeout("timed out")
    if source.name == "empty-source":
        return []
    return [
        Article(source.name, source.section, "A title", "https://ok.example/a",
                published=datetime.now(UTC))
    ]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # Every test in this file uses fake_fetch instead of the real feed fetcher,
    # and a fake page download in fetch_text.
    monkeypatch.setitem(FETCHERS, "feed", fake_fetch)
    monkeypatch.setattr("digest.nodes.fetch_text.extract_text", lambda client, url: "word " * 200)


def test_collect_returns_articles_and_metrics():
    result = collect({"source": OK})

    assert len(result["collected"]) == 1
    assert result["errors"] == []
    [metrics] = result["metrics"]
    assert metrics.node == "collect:ok-source"
    assert metrics.counts == {"articles": 1}


def test_collect_waits_before_the_request_when_asked(monkeypatch):
    waits = []
    monkeypatch.setattr("digest.nodes.collect.time.sleep", waits.append)
    slow = Source("reddit/MachineLearning", "feed", "data", "https://ok.example/rss", delay_s=10)

    collect({"source": slow})

    assert waits == [10]


def test_empty_feed_is_recorded_as_an_anomaly():
    empty = Source("empty-source", "feed", "data", "https://empty.example/rss")

    result = collect({"source": empty})

    assert result["collected"] == []
    assert result["errors"] == [SourceError("empty-source", "empty feed")]


def test_collect_records_error_instead_of_raising():
    result = collect({"source": BROKEN})

    assert result["collected"] == []
    assert result["errors"] == [SourceError("broken-source", "ConnectTimeout")]
    assert result["metrics"][0].counts == {"articles": 0}


def test_graph_runs_every_source_and_merges_results(tmp_path, monkeypatch):
    monkeypatch.setattr("digest.nodes.render_epub.OUT_DIR", tmp_path)
    monkeypatch.delenv("SEND", raising=False)

    state = build_graph([OK, BROKEN], FakeLLM(), FakeLLM()).invoke({})

    assert [a.source for a in state["collected"]] == ["ok-source"]
    assert [e.source for e in state["errors"]] == ["broken-source"]
    # One measure per source, even the broken one, then one per following node.
    assert [m.node for m in state["metrics"]] == [
        "collect:ok-source", "collect:broken-source", "clean", "rank", "select", "fetch_text",
        "summarize:ok-source", "render_epub", "deliver",
    ]
    assert [a.source for a in state["cleaned"]] == ["ok-source"]
    assert [a.source for a in state["ranked"]] == ["ok-source"]
    assert [a.source for a in state["selected"]] == ["ok-source"]
    assert state["selected"][0].text  # fake page text, no network
    assert [c.model for c in state["llm_calls"]] == ["fake", "fake"]  # rank + 1 summary
    assert state["epub_path"].startswith(str(tmp_path))
