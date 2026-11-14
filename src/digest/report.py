"""Run report: one JSON file per run with counts, durations, tokens, cost and errors.

Written after the graph, the only place that knows the total duration.
The measure does not depend on any LLM: plain arithmetic on what was recorded.
"""

import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from digest.nodes.rank import PROMPT_VERSION as RANK_PROMPT
from digest.nodes.summarize import PROMPT_VERSION as SUMMARIZE_PROMPT
from digest.paths import ROOT
from digest.state import DigestState

RUNS_DIR = ROOT / "runs"  # real runs: versioned
FAKE_DIR = ROOT / "out"  # --fake runs: ignored by git


def git_sha() -> str | None:
    if os.environ.get("GITHUB_SHA"):  # set by GitHub Actions
        return os.environ["GITHUB_SHA"][:7]
    # check=False: outside a git repository, the report just has no sha.
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False, capture_output=True, text=True, cwd=ROOT,
    )
    return result.stdout.strip() or None


def write_run_report(
    state: DigestState, seconds: float, llm, now: datetime | None = None
) -> Path:
    today = now or datetime.now(ZoneInfo("Europe/Paris"))
    calls = state.get("llm_calls", [])
    fake = llm.model == "fake"
    selected_urls = {a.url for a in state.get("selected", [])}
    report = {
        "date": f"{today:%Y-%m-%d}",
        "finished_at": today.isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "mode": "fake" if fake else "real",
        "config": {
            "model": llm.model,
            "effort": getattr(llm, "effort", None),
            "prompts": {"rank": RANK_PROMPT, "summarize": SUMMARIZE_PROMPT},
        },
        "counts": {
            "collected": len(state.get("collected", [])),
            "after_clean": len(state.get("cleaned", [])),
            "selected": len(state.get("selected", [])),
            "summarized": sum(bool(a.summary) for a in state.get("summarized", [])),
            "raw": sum(a.raw for a in state.get("selected", [])),
        },
        "totals": {
            "seconds": round(seconds, 2),
            "llm_calls": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "thinking_tokens": sum(c.thinking_tokens for c in calls),
            "cache_read_input_tokens": sum(c.cache_read_input_tokens for c in calls),
            "cost_usd": round(sum(c.cost_usd for c in calls), 6),
        },
        "nodes": [asdict(m) for m in state.get("metrics", [])],
        "llm_calls": [asdict(c) for c in calls],
        "errors": [asdict(e) for e in state.get("errors", [])],
        # Every candidate with its score: answers "why was this kept, or not?"
        # and is the raw material for evaluating the ranking against my own judgment.
        "candidates": [
            {"source": a.source, "section": a.section, "title": a.title, "score": a.score,
             "topic": a.topic, "selected": a.url in selected_urls}
            for a in state.get("ranked", [])
        ],
    }
    folder = FAKE_DIR if fake else RUNS_DIR
    folder.mkdir(exist_ok=True)
    # Date and time (Paris) in the name: several runs on the same day must not overwrite each other.
    stamp = f"{today:%Y-%m-%d_%H%M}"
    path = folder / (f"run-{stamp}-fake.json" if fake else f"{stamp}.json")
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path
