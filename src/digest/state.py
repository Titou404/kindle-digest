"""Shared state passed between the nodes of the digest graph."""

import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, TypedDict


@dataclass
class Article:
    source: str  # e.g. "hackernews", "reddit/datascience", "lemonde/eco"
    section: str  # "data", "monde", "eco" or "france" (quotas in select)
    title: str
    url: str
    published: datetime | None = None
    snippet: str = ""  # short intro from the feed, read by the rank node
    text: str = ""  # full text, filled by the fetch_text node
    summary: str = ""  # filled by the summarize node


@dataclass
class SourceError:
    source: str
    error: str  # e.g. "HTTP 429"


@dataclass
class NodeMetrics:
    node: str
    duration_s: float
    # e.g. {"articles_in": 120, "articles_out": 80}
    counts: dict[str, int] = field(default_factory=dict)


class DigestState(TypedDict, total=False):
    # Written by several collector nodes running in parallel: lists are concatenated.
    collected: Annotated[list[Article], operator.add]
    # Each written by a single node: the new value replaces the old one.
    cleaned: list[Article]
    selected: list[Article]
    epub_path: str
    # Any node may append to these.
    errors: Annotated[list[SourceError], operator.add]
    metrics: Annotated[list[NodeMetrics], operator.add]
