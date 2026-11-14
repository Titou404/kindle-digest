import argparse
import sys
import time

from digest.graph import build_graph
from digest.llm import make_llm
from digest.report import write_run_report
from digest.sources import load_sources


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="digest",
        description="Build the daily digest and send it to the Kindle.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="use a fake LLM instead of the Anthropic API (no paid calls)",
    )
    args = parser.parse_args(argv)

    mode = "fake" if args.fake else "real"
    print(f"digest: running in {mode} mode")

    llm = make_llm(fake=args.fake)
    start = time.perf_counter()
    state = build_graph(load_sources(), llm).invoke({})
    elapsed = time.perf_counter() - start
    report_path = write_run_report(state, elapsed, llm)

    for m in state["metrics"]:
        counts = ", ".join(f"{key}={value}" for key, value in m.counts.items())
        print(f"  {m.node:<30}{m.duration_s:>6.2f}s  {counts}")
    for c in state["llm_calls"]:
        print(f"  llm:{c.task:<26}{c.latency_s:>6.2f}s  model={c.model}, in={c.input_tokens}, "
              f"out={c.output_tokens}, thinking={c.thinking_tokens}, cost=${c.cost_usd:.4f}")
    for e in state["errors"]:
        print(f"  error: {e.source}: {e.error}")
    cost = sum(c.cost_usd for c in state["llm_calls"])
    print(f"{len(state['collected'])} collected -> {len(state['cleaned'])} after clean -> "
          f"{len(state['summarized'])} in the journal, {len(state['errors'])} error(s), "
          f"{elapsed:.2f}s, ${cost:.4f}")
    print(f"journal: {state['epub_path']}")
    print(f"report:  {report_path}")

    # A source down is not a failure (the journal still goes out), a failed email is:
    # a non-zero exit code turns the GitHub Actions run red, and GitHub sends an alert.
    if any(e.source == "deliver" for e in state["errors"]):
        sys.exit(1)
