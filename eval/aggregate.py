"""Gather every result of the bench into one JSON file: the data of the "config" page.

Usage: uv run python eval/aggregate.py [--day 2026-11-15]
Reads eval/results/<day>/ (bench runs, checks.json, judge/, rank_quality.json) and the frozen
day, writes eval/results/<day>/summary.json. Plain arithmetic, no LLM: every number of the
page comes from this file, none is typed by hand.
"""

import argparse
import json
import re
import statistics
from collections import Counter
from itertools import combinations

from bench import FIXTURES_DIR, RESULTS_DIR, load_fixture
from rank_quality import auc, load_labels

from digest.nodes.fetch_text import MAX_TEXT
from digest.nodes.select import QUOTAS
from digest.pricing import PRICES

RUN_FILE = re.compile(r"([SR]\d+)-(\d+)\.json")
# Comments on the source rather than on the news ("published by franceinfo", "the text is
# cut"): the summarizer saw the source name in the <article> tag, the judge did not.
META = re.compile(r"The Conversation|franceinfo|tronqu|suite de l'article", re.IGNORECASE)
SECTIONS = ["data", "monde", "eco", "france"]
# The first pass of check_facts.py, before it learnt scales, rounding, titles and versions.
# That version of the script is gone, so this record is kept by hand (see CLAUDE.md, 2026-11-15).
CHECKS_FIRST_PASS = {
    "false_alarms": 23,
    "examples": ["« 10.7k » devenu « 10 700 »", "des arrondis (93,4 % en 93 %)",
                 "un nombre du titre", "un numéro de version"],
}


def auc_margin95(value: float, n_kept: int, n_dropped: int) -> float:
    """Half-width of the 95 % confidence interval of an AUC (Hanley and McNeil, 1982)."""
    q1, q2 = value / (2 - value), 2 * value**2 / (1 + value)
    variance = (value * (1 - value) + (n_kept - 1) * (q1 - value**2)
                + (n_dropped - 1) * (q2 - value**2)) / (n_kept * n_dropped)
    return round(1.96 * variance**0.5, 3)


def mean(xs):
    return round(statistics.mean(xs), 4) if xs else None


def selected_urls(run: dict) -> set[str]:
    return {i["url"] for i in run["items"] if i["selected"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gather the bench results for the config page.")
    parser.add_argument("--day", default="2026-11-15", help="frozen day (fixture name)")
    args = parser.parse_args()
    folder = RESULTS_DIR / args.day

    candidates, articles, meta = load_fixture(FIXTURES_DIR / f"{args.day}.json")
    short = min(articles, key=lambda a: len(a.text))
    runs = {}
    for path in sorted(folder.iterdir()):
        match = RUN_FILE.fullmatch(path.name)
        if match:
            runs[path.stem] = json.loads(path.read_text())
    checks = json.loads((folder / "checks.json").read_text())["totals"]
    rank_quality = json.loads((folder / "rank_quality.json").read_text())
    judged = [json.loads(p.read_text()) for p in sorted((folder / "judge" / "v2").glob("*.json"))]
    judged_v1 = [json.loads(p.read_text()) for p in sorted((folder / "judge" / "v1").glob("*.json"))]

    def reps(cid):
        return [r for name, r in runs.items() if name.split("-")[0] == cid]

    # ---------- Summaries ----------
    summaries = []
    for cid in sorted({r["config"]["id"] for r in runs.values() if r["config"]["task"] == "summarize"}):
        rs = reps(cid)
        items = [i for r in rs for i in r["items"] if i["summary"]]
        judgments = [j for j in judged if j["config"] == cid]
        claims = [c for j in judgments for c in j["judgment"]["claims"]]
        unsupported = [c for c in claims if c["verdict"] != "soutenue"]
        why = Counter(j["scores"]["why_it_matters"] for j in judgments)
        summaries.append({
            "id": cid, "config": rs[0]["config"], "repeats": len(rs),
            "cost_ct": round(mean([r["totals"]["cost_usd"] for r in rs]) * 100, 3),
            "latency_s": mean([r["totals"]["mean_latency_s"] for r in rs]),
            "thinking": mean([r["totals"]["thinking_tokens"] for r in rs]),
            "input_tokens": mean([r["totals"]["input_tokens"] for r in rs]),
            "words": {"mean": round(statistics.mean(i["words"] for i in items)),
                      "min": min(i["words"] for i in items), "max": max(i["words"] for i in items)},
            "short_article_words": [i["words"] for r in rs for i in r["items"] if i["url"] == short.url],
            "checks": checks[cid],
            "judge": {
                "summaries": len(judgments), "claims": len(claims), "unsupported": len(unsupported),
                "meta": sum(bool(META.search(c["claim"])) for c in unsupported),
                "content": sum(not META.search(c["claim"]) for c in unsupported),
                "omissions": sum(len(j["judgment"]["omissions"]) for j in judgments),
                "why": {k: why.get(k, 0) for k in
                        ["tiree_du_texte", "deduction_raisonnable", "fait_exterieur"]},
                "cost_usd": round(sum(j["llm_call"]["cost_usd"] for j in judgments), 4),
            },
        })

    flags = []
    for j in judged:
        for c in j["judgment"]["claims"]:
            if c["verdict"] != "soutenue":
                flags.append({"config": j["config"], "title": j["title"], "kind": "claim",
                              "category": "meta" if META.search(c["claim"]) else "content",
                              "text": c["claim"], "why": c["evidence"]})
        w = j["judgment"]["why_it_matters"]
        if w["verdict"] == "fait_exterieur":
            flags.append({"config": j["config"], "title": j["title"], "kind": "why",
                          "category": "external", "text": "Phrase « pourquoi c'est important »",
                          "why": w["explanation"]})
        for o in j["judgment"]["omissions"]:
            flags.append({"config": j["config"], "title": j["title"], "kind": "omission",
                          "category": "omission", "text": "Point essentiel oublié", "why": o})

    # The v1 judge contradicting its own evidence: the reason for v2.
    v1_contradiction = next(
        ({"claim": c["claim"], "evidence": c["evidence"]}
         for j in judged_v1 for c in j["judgment"]["claims"] if c["verdict"] != "soutenue"),
        None)

    # ---------- Ranking ----------
    labels = load_labels(args.day)
    quality = rank_quality["runs"]
    r4 = [selected_urls(r) for name, r in runs.items() if name.startswith("R4-")]
    rankings = []
    for cid in sorted({r["config"]["id"] for r in runs.values() if r["config"]["task"] == "rank"}):
        names = sorted(n for n in runs if n.split("-")[0] == cid)
        rankings.append({
            "id": cid, "config": runs[names[0]]["config"],
            "runs": [{
                "name": n,
                "cost_ct": round(runs[n]["totals"]["cost_usd"] * 100, 3),
                "seconds": runs[n]["totals"]["seconds"],
                "thinking": runs[n]["totals"]["thinking_tokens"],
                "precision": quality[n]["precision"], "auc": quality[n]["auc"],
                "common_with_sonnet": [len(selected_urls(runs[n]) & s) for s in r4],
            } for n in names],
            "common_between_repeats": [len(selected_urls(runs[a]) & selected_urls(runs[b]))
                                       for a, b in combinations(names, 2)],
        })

    # Mean score of each candidate over every single-call run: a steadier view of "the model".
    batched = [r for n, r in runs.items() if n[0] == "R" and r["config"]["mode"] == "batched"]
    scores, info = {}, {}
    for r in batched:
        for i in r["items"]:
            scores.setdefault(i["url"], []).append(i["score"] or 0)
            info[i["url"]] = i
    avg = {u: statistics.mean(s) for u, s in scores.items()}
    by_section = []
    for section in SECTIONS:
        urls = [u for u in labels if info[u]["section"] == section]
        kept = [avg[u] for u in urls if labels[u]]
        dropped = [avg[u] for u in urls if not labels[u]]
        by_section.append({"section": section, "kept": len(kept), "dropped": len(dropped),
                           "auc": round(auc(kept, dropped), 3)})

    def disagreement(urls):
        return [{"title": info[u]["title"], "source": info[u]["source"],
                 "score": round(avg[u], 1)} for u in urls]

    kept_low = sorted((u for u in labels if labels[u]), key=lambda u: avg[u])[:6]
    dropped_high = sorted((u for u in labels if not labels[u]), key=lambda u: -avg[u])[:6]

    # ---------- Bench cost ----------
    def series_cost(models):
        return round(sum(r["totals"]["cost_usd"] for r in runs.values()
                         if r["config"]["model"] in models), 4)

    cost = {
        "haiku_runs": series_cost({"claude-haiku-5-5"}),
        "sonnet_runs": series_cost({"claude-sonnet-5-5"}),
        "judge_v1": round(sum(j["llm_call"]["cost_usd"] for j in judged_v1), 4),
        "judge_v2": round(sum(j["llm_call"]["cost_usd"] for j in judged), 4),
    }
    cost["total"] = round(sum(cost.values()), 4)

    rank_runs = [{"auc": u["auc"], "batched": r["config"]["mode"] == "batched"}
                 for r in rankings for u in r["runs"]]
    by_id = {s["id"]: s for s in summaries} | {r["id"]: r for r in rankings}
    retained = {
        "rank": "R2", "summarize": "S7",
        "cost_ct": round(statistics.mean(x["cost_ct"] for x in by_id["R2"]["runs"])
                         + by_id["S7"]["cost_ct"], 2),
    }
    summary = {
        "day": args.day,
        "fixture": {"candidates": len(candidates), "articles": len(articles),
                    "articles_by_section": Counter(a.section for a in articles),
                    "frozen_at": meta["frozen_at"],
                    "short_article": {"title": short.title, "chars": len(short.text),
                                      "words": len(short.text.split())}},
        "cost": cost, "retained": retained,
        "summaries": summaries, "flags": flags, "judge_v1_contradiction": v1_contradiction,
        "rankings": rankings,
        "labels": {"total": len(labels), "kept": sum(labels.values()),
                   "chance_precision": rank_quality["chance_precision"],
                   "auc_margin95": auc_margin95(
                       statistics.mean(r["auc"] for r in rank_runs if r["batched"]),
                       sum(labels.values()), len(labels) - sum(labels.values()))},
        "settings": {"max_text": MAX_TEXT, "journal_size": sum(QUOTAS.values()),
                     "prices": {m: PRICES[m] for m in ("claude-haiku-5-5", "claude-sonnet-5-5")}},
        "checks_first_pass": CHECKS_FIRST_PASS,
        "rank_by_section": by_section,
        "disagreements": {"kept_scored_low": disagreement(kept_low),
                          "dropped_scored_high": disagreement(dropped_high)},
    }
    out = folder / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"summary: {out} ({len(summaries)} summary configs, {len(rankings)} ranking configs, "
          f"{len(flags)} judge flags, bench ${cost['total']:.2f}, retained config "
          f"{retained['cost_ct']} ct per journal)")


if __name__ == "__main__":
    main()
