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
PARIS = ZoneInfo("Europe/Paris")
# Who started the runs written before the report recorded it (from `gh run list`, 2026-11-15).
# Reports keep their raw content: this table completes the index instead.
KNOWN_TRIGGERS = {
    "2026-11-14_1808": "local",  # before the workflow existed
    "2026-11-14_1934": "workflow_dispatch",
    "2026-11-14_1956": "workflow_dispatch",
    "2026-11-14_2215": "workflow_dispatch",
    "2026-11-15_1220": "workflow_dispatch",
    "2026-11-15_1311": "schedule",  # the first cron run, 7 h 40 late
}


def write_runs_index(folder: Path) -> Path:
    """List every run report, newest first, with who started it.

    A static web page cannot list a folder: it reads this index, then the reports it names.
    Trigger: "schedule" (the daily cron), "workflow_dispatch" (started by hand on GitHub)
    or "local" (on a computer).
    """
    runs = []
    for path in sorted(folder.glob("????-??-??_????.json"), reverse=True):
        report = json.loads(path.read_text())
        # The first reports have no finished_at: the name holds the same date and time.
        finished = report.get("finished_at") or datetime.strptime(
            path.stem, "%Y-%m-%d_%H%M").replace(tzinfo=PARIS).isoformat()
        trigger = report.get("trigger") or KNOWN_TRIGGERS.get(path.stem, "local")
        runs.append({"file": path.name, "finished_at": finished, "trigger": trigger})
    index = folder / "index.json"
    index.write_text(json.dumps({"runs": runs}, indent=2) + "\n")
    return index


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
    state: DigestState, seconds: float, llms: dict, now: datetime | None = None
) -> Path:
    """llms: the LLM of each task, e.g. {"rank": ..., "summarize": ...}."""
    today = now or datetime.now(PARIS)
    calls = state.get("llm_calls", [])
    fake = all(llm.model == "fake" for llm in llms.values())
    selected_urls = {a.url for a in state.get("selected", [])}
    report = {
        "date": f"{today:%Y-%m-%d}",
        "finished_at": today.isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "mode": "fake" if fake else "real",
        # Set by GitHub Actions: "schedule" (the daily cron) or "workflow_dispatch" (by hand).
        # None on a computer. The monitoring page shows the cron runs only.
        "trigger": os.environ.get("GITHUB_EVENT_NAME"),
        # Per task since 2026-11-15 (earlier reports have a single model and effort).
        "config": {
            "model": {task: llm.model for task, llm in llms.items()},
            "effort": {task: getattr(llm, "effort", None) for task, llm in llms.items()},
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
    if not fake:
        write_runs_index(folder)  # committed with the report by the workflow (git add runs/)
    return path
