"""Collect node: fetch the articles of one source.

The graph runs it once per source, in parallel (see Send in graph.py).
"""

import time
from typing import TypedDict

from digest.collectors import FETCHERS, describe_error, make_client
from digest.sources import Source
from digest.state import NodeMetrics, SourceError


class CollectInput(TypedDict):
    source: Source


def collect(state: CollectInput) -> dict:
    source = state["source"]
    start = time.perf_counter()
    articles, errors = [], []
    # Broad except on purpose: a source that fails must not stop the run.
    # The error is recorded in the state instead.
    try:
        with make_client() as client:
            articles = FETCHERS[source.kind](client, source)
    except Exception as e:  # noqa: BLE001
        errors.append(SourceError(source=source.name, error=describe_error(e)))

    metrics = NodeMetrics(
        node=f"collect:{source.name}",
        duration_s=round(time.perf_counter() - start, 3),
        counts={"articles": len(articles)},
    )
    return {"collected": articles, "errors": errors, "metrics": [metrics]}
