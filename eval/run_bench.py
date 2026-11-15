"""Run the evaluation bench on a frozen day.

Usage:
  uv run python eval/run_bench.py                    # every config, fake LLM: free
  uv run python eval/run_bench.py --only S1,R1       # some configs only
  uv run --env-file .env python eval/run_bench.py --real --only S1   # paid calls

Fake by default, unlike the pipeline: here a typo could start a whole series of paid
Sonnet calls, so spending has to be asked for explicitly with --real. A real result
already on disk is never run again (no paying twice), unless --force.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bench import (
    FAKE_DIR,
    FIXTURES_DIR,
    RESULTS_DIR,
    load_configs,
    load_fixture,
    run_config,
)

from digest.llm import ClaudeLLM, FakeLLM
from digest.report import git_sha


def latest_fixture() -> Path:
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        raise SystemExit("no frozen day in eval/fixtures/: run eval/freeze_day.py first")
    return fixtures[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation bench on a frozen day.")
    parser.add_argument("--real", action="store_true", help="call the Anthropic API (paid)")
    parser.add_argument("--only", help="comma-separated config ids, e.g. S1,S2,R1")
    parser.add_argument("--fixture", type=Path, help="frozen day (default: the latest)")
    parser.add_argument("--force", action="store_true", help="rerun real results on disk")
    args = parser.parse_args()

    fixture = args.fixture or latest_fixture()
    candidates, articles, _ = load_fixture(fixture)
    configs = load_configs()
    if args.only:
        wanted = args.only.split(",")
        unknown = set(wanted) - {c.id for c in configs}
        if unknown:
            raise SystemExit(f"unknown config ids: {sorted(unknown)}")
        configs = [c for c in configs if c.id in wanted]

    out_dir = (RESULTS_DIR if args.real else FAKE_DIR) / fixture.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"bench: {'REAL (paid)' if args.real else 'fake'} mode, fixture {fixture.name}: "
          f"{len(candidates)} candidates, {len(articles)} articles")

    spent = 0.0
    for config in configs:
        for repeat in range(1, config.repeats + 1):
            path = out_dir / f"{config.id}-{repeat}.json"
            if args.real and path.exists() and not args.force:
                print(f"  {config.id}-{repeat}: already on disk, skipped")
                continue
            llm = ClaudeLLM(model=config.model, effort=config.effort) if args.real else FakeLLM()
            result = run_config(config, candidates, articles, llm)
            now = datetime.now(ZoneInfo("Europe/Paris"))
            result = {
                "fixture": fixture.stem, "repeat": repeat,
                "mode": "real" if args.real else "fake",
                "finished_at": now.isoformat(timespec="seconds"), "git_sha": git_sha(),
                **result,
            }
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1))

            t = result["totals"]
            spent += t["cost_usd"]
            items = result["items"]
            if config.task == "summarize":
                words = [i["words"] for i in items if i["summary"]]
                detail = f"{len(words)} summaries, {min(words, default=0)}-{max(words, default=0)} words"
            else:
                detail = f"{sum(i['selected'] for i in items)} selected"
            print(f"  {config.id}-{repeat}: {t['llm_calls']} calls, ${t['cost_usd']:.4f}, "
                  f"{t['seconds']:.1f}s, thinking={t['thinking_tokens']}, {detail}, "
                  f"{len(result['errors'])} error(s)")
    print(f"total spent: ${spent:.4f}   results: {out_dir}")


if __name__ == "__main__":
    main()
