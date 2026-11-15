"""Quality of the ranking configs, measured against Mazou's own labels (keep = 1, drop = 0).

Usage: uv run python eval/rank_quality.py [--day 2026-11-15]
Reads eval/labels/<day>.csv (ignored by git: it holds the snippets), writes the labels reduced
to link and verdict in eval/results/<day>/labels.json, and the scores in rank_quality.json.

Two measures, both exact arithmetic on the labels (a script, no LLM):
- precision: among the 12 articles a config put in the journal, the share Mazou would keep.
  What he reads every morning, but noisy (12 articles). Picking at random gives the share
  of kept articles among all candidates.
- AUC: draw an article he keeps and one he drops; the probability that the config scored the
  kept one higher (a tie counts half). 0.5 is chance, 1.0 is perfect. It uses the scores of
  every candidate, not only the 12 selected, so it is less noisy.
"""

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict

from bench import EVAL_DIR, RESULTS_DIR

RANK_FILE = re.compile(r"R\d+-\d+\.json")


def load_labels(day: str) -> dict[str, int]:
    raw = (EVAL_DIR / "labels" / f"{day}.csv").read_text(encoding="utf-8-sig")
    delimiter = ";" if raw.count(";") > raw.count(",") else ","  # Excel or Numbers export
    rows = csv.DictReader(raw.splitlines(), delimiter=delimiter)
    return {row["lien"]: int(row["garder"]) for row in rows if row["garder"].strip()}


def auc(scores_kept: list[float], scores_dropped: list[float]) -> float:
    wins = sum(1.0 if k > d else 0.5 if k == d else 0.0
               for k in scores_kept for d in scores_dropped)
    return wins / (len(scores_kept) * len(scores_dropped))


def quality(items: list[dict], labels: dict[str, int]) -> dict:
    labeled = [i for i in items if i["url"] in labels]
    selected = [i for i in labeled if i["selected"]]
    kept = [i["score"] or 0 for i in labeled if labels[i["url"]] == 1]
    dropped = [i["score"] or 0 for i in labeled if labels[i["url"]] == 0]
    return {
        "precision": round(sum(labels[i["url"]] for i in selected) / len(selected), 3),
        "selected": len(selected),
        "auc": round(auc(kept, dropped), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the ranking configs against my labels.")
    parser.add_argument("--day", default="2026-11-15", help="frozen day (fixture name)")
    args = parser.parse_args()

    labels = load_labels(args.day)
    folder = RESULTS_DIR / args.day
    runs, by_config = {}, defaultdict(list)
    for path in sorted(p for p in folder.iterdir() if RANK_FILE.fullmatch(p.name)):
        result = json.loads(path.read_text())
        q = {**quality(result["items"], labels), "cost_usd": result["totals"]["cost_usd"],
             "thinking_tokens": result["totals"]["thinking_tokens"]}
        runs[path.stem] = q
        by_config[result["config"]["id"]].append(q)
        titles = {i["url"]: i["title"] for i in result["items"]}

    base_rate = sum(labels.values()) / len(labels)
    (folder / "labels.json").write_text(json.dumps(
        [{"url": url, "title": titles.get(url, ""), "keep": keep} for url, keep in labels.items()],
        ensure_ascii=False, indent=1))
    (folder / "rank_quality.json").write_text(json.dumps(
        {"labels": len(labels), "kept": sum(labels.values()), "chance_precision": round(base_rate, 3),
         "runs": runs}, ensure_ascii=False, indent=1))

    print(f"{len(labels)} étiquettes, {sum(labels.values())} à garder : "
          f"au hasard, précision ≈ {base_rate:.0%} et AUC = 50 %\n")
    print(f"{'config':<7}{'précision (12 retenus)':>26}{'AUC (89 candidats)':>24}{'coût moyen':>12}")
    for cid in sorted(by_config):
        qs = by_config[cid]
        p = [q["precision"] for q in qs]
        a = [q["auc"] for q in qs]
        spread = lambda xs: f"{statistics.mean(xs):.0%} ({min(xs):.0%}–{max(xs):.0%})"
        print(f"{cid:<7}{spread(p):>26}{spread(a):>24}"
              f"{statistics.mean(q['cost_usd'] for q in qs) * 100:>10.2f} ct")
    print("\npar run :")
    for name, q in runs.items():
        print(f"  {name:<6} précision {q['precision']:.0%}  AUC {q['auc']:.0%}  "
              f"thinking {q['thinking_tokens']:>5}")


if __name__ == "__main__":
    main()
