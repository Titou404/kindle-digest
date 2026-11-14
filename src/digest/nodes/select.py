"""Select node: keep the best articles of each section, with quotas.

Sorting numbers and applying quotas has an exact answer: a script, no LLM.
"""

import time
from datetime import UTC, datetime

from digest.state import Article, DigestState, NodeMetrics

QUOTAS = {"data": 3, "monde": 3, "eco": 3, "france": 3}  # "balanced" choice: 12 articles
OLDEST = datetime.min.replace(tzinfo=UTC)


def select_articles(
    ranked: list[Article], quotas: dict[str, int] = QUOTAS
) -> tuple[list[Article], dict[str, int]]:
    # If every score is 0, rank failed: fall back to the most recent articles.
    rank_failed = all(not a.score for a in ranked)
    # Otherwise a 0 means "excluded by the profile" (or not scored): never selected.
    candidates = ranked if rank_failed else [a for a in ranked if a.score]
    # Best score first; on a tie (or when rank failed), the most recent first.
    candidates = sorted(candidates, key=lambda a: (a.score or 0, a.published or OLDEST), reverse=True)

    selected, seen_topics, duplicate_topics = [], set(), 0
    for section, quota in quotas.items():
        kept = 0
        for article in candidates:
            if kept == quota:
                break
            if article.section != section:
                continue
            topic = article.topic.casefold()
            if topic and topic in seen_topics:  # same event already in the journal
                duplicate_topics += 1
                continue
            seen_topics.add(topic)
            selected.append(article)
            kept += 1

    counts = {
        "candidates": len(candidates),
        "selected": len(selected),
        "duplicate_topics": duplicate_topics,
        "rank_failed": int(rank_failed),
    }
    return selected, counts


def select(state: DigestState) -> dict:
    start = time.perf_counter()
    selected, counts = select_articles(state["ranked"])
    metrics = NodeMetrics("select", round(time.perf_counter() - start, 3), counts)
    return {"selected": selected, "metrics": [metrics]}
