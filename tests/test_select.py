"""Tests for the select node's rules."""

from datetime import UTC, datetime, timedelta

from digest.nodes.select import select_articles
from digest.state import Article

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)


def article(section, score, topic="", hours_ago=1, title=None):
    return Article(
        "source", section, title or f"{section} {score} {topic}", "https://example.com",
        published=NOW - timedelta(hours=hours_ago), score=score, topic=topic,
    )


def test_best_scores_first_within_each_quota():
    ranked = [article("data", s) for s in (2, 9, 5, 7)] + [article("monde", 8)]

    selected, _ = select_articles(ranked, {"data": 2, "monde": 1})

    assert [(a.section, a.score) for a in selected] == [("data", 9), ("data", 7), ("monde", 8)]


def test_same_topic_is_kept_only_once():
    ranked = [
        article("monde", 9, "arrêt des vols"),
        article("monde", 8, "Arrêt des vols"),  # same event, case differs
        article("monde", 6, "sommet de l'OTAN"),
    ]

    selected, counts = select_articles(ranked, {"monde": 2})

    assert [a.score for a in selected] == [9, 6]
    assert counts["duplicate_topics"] == 1


def test_score_zero_is_never_selected():
    selected, _ = select_articles([article("data", 0), article("data", 3)], {"data": 3})

    assert [a.score for a in selected] == [3]


def test_when_rank_failed_the_most_recent_articles_are_kept():
    ranked = [article("data", 0, hours_ago=h, title=f"{h}h ago") for h in (5, 1, 3)]

    selected, counts = select_articles(ranked, {"data": 2})

    assert [a.title for a in selected] == ["1h ago", "3h ago"]
    assert counts["rank_failed"] == 1
