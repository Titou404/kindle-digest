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
    text: str = ""  # full text: from the feed if included, else from fetch_text
    summary: str = ""  # filled by the summarize node
    why_it_matters: str = ""  # one sentence, filled by the summarize node
    score: int | None = None  # 0 to 10, set by the rank node
    topic: str = ""  # short subject, set by the rank node (same event, same topic)
    raw: bool = False  # from a raw source: shown as written, never summarized


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


@dataclass
class LLMCall:
    """One call to the model: what it cost and how long it took."""

    task: str  # e.g. "rank", "summarize"
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int  # thinking tokens are billed as output and counted here
    thinking_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    latency_s: float
    cost_usd: float
    stop_reason: str  # "end_turn" when the answer is complete
    request_id: str | None = None  # to find the call in the Anthropic console


class DigestState(TypedDict, total=False):
    # Written by several collector nodes running in parallel: lists are concatenated.
    collected: Annotated[list[Article], operator.add]
    # Each written by a single node: the new value replaces the old one.
    cleaned: list[Article]
    ranked: list[Article]
    selected: list[Article]
    # Written by the parallel summarize runs, one article each: lists are concatenated.
    summarized: Annotated[list[Article], operator.add]
    epub_path: str
    # Any node may append to these.
    errors: Annotated[list[SourceError], operator.add]
    metrics: Annotated[list[NodeMetrics], operator.add]
    llm_calls: Annotated[list[LLMCall], operator.add]
