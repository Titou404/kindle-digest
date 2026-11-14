"""Build the digest graph."""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from digest.llm import LLM
from digest.nodes.clean import clean
from digest.nodes.collect import collect
from digest.nodes.deliver import deliver
from digest.nodes.fetch_text import fetch_text
from digest.nodes.rank import rank
from digest.nodes.render_epub import render_epub
from digest.nodes.select import select
from digest.nodes.summarize import SummarizeInput, summarize
from digest.sources import Source
from digest.state import DigestState


def build_graph(sources: list[Source], llm: LLM):
    # The sources and the LLM (real or fake) are given from outside: the nodes that
    # need them reach them through these inner functions (closures).
    def dispatch_sources(_state: DigestState) -> list[Send]:
        # One "collect" run per source, all in parallel.
        return [Send("collect", {"source": source}) for source in sources]

    def dispatch_summaries(state: DigestState) -> list[Send] | str:
        # One "summarize" run per selected article, all in parallel.
        # Nothing selected: go straight to the journal (it will hold the report page).
        if not state["selected"]:
            return "render_epub"
        return [Send("summarize", {"article": article}) for article in state["selected"]]

    def rank_node(state: DigestState) -> dict:
        return rank(state, llm)

    def summarize_node(state: SummarizeInput) -> dict:
        return summarize(state, llm)

    graph = StateGraph(DigestState)
    graph.add_node("collect", collect)
    graph.add_node("clean", clean)
    graph.add_node("rank", rank_node)
    graph.add_node("select", select)
    graph.add_node("fetch_text", fetch_text)
    graph.add_node("summarize", summarize_node)
    graph.add_node("render_epub", render_epub)
    graph.add_node("deliver", deliver)

    graph.add_conditional_edges(START, dispatch_sources, ["collect"])
    # "clean" runs once, after every parallel "collect" run has finished.
    graph.add_edge("collect", "clean")
    graph.add_edge("clean", "rank")
    graph.add_edge("rank", "select")
    graph.add_edge("select", "fetch_text")
    graph.add_conditional_edges("fetch_text", dispatch_summaries, ["summarize", "render_epub"])
    # Same as for "clean": "render_epub" waits for every parallel "summarize" run.
    graph.add_edge("summarize", "render_epub")
    graph.add_edge("render_epub", "deliver")
    graph.add_edge("deliver", END)
    return graph.compile()
