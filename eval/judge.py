"""LLM judge of the bench summaries: claim-by-claim fidelity, class of the "why it matters"
sentence, and essential points left out.

Usage:
  uv run python eval/judge.py                                     # fake judge: free
  uv run --env-file .env python eval/judge.py --real --limit 3    # 3 paid test calls
  uv run --env-file .env python eval/judge.py --real              # every judged summary

Whether a claim is supported by a text is a language judgment, hence an LLM; counting and
averaging the verdicts is exact, hence this script. The judge is blind: it never sees which
config wrote the summary, and each summary is judged alone (no side-by-side comparison, so no
position bias). It always gets the full article (up to 20,000 characters): a summary written
from a cut text (S4) can then show what the cut made it miss. One repetition per config is
judged (7 configs x 12 summaries). A real judgment already on disk is never paid twice.
"""

import argparse
import hashlib
import html
import json
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from bench import FAKE_DIR, FIXTURES_DIR, RESULTS_DIR, load_fixture

from digest.llm import ClaudeLLM, FakeLLM, LLMOutputError
from digest.paths import PROMPTS_DIR

JUDGE_MODEL = "claude-sonnet-5-5"
JUDGE_EFFORT = "medium"
# v2 (2026-11-15): evidence before verdict, stricter omissions. v1 contradicted its own
# evidence once in 3 test calls, and listed details as omissions.
PROMPT_VERSION = "v2"
MAX_TOKENS = 8000  # ~12 claims with their evidence, plus room for thinking
REPEAT = 1  # the repetition of each config that is judged
SEED = 15  # fixed shuffle: --limit always picks the same summaries, in a mixed order
WORKERS = 4  # parallel calls: modest, to stay under the account's rate limits
SUMMARY_FILE = re.compile(r"S\d+-(\d+)\.json")
WHY_CLASSES = ["tiree_du_texte", "deduction_raisonnable", "fait_exterieur"]
SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                # Evidence before verdict: the model writes its proof, then decides from it
                # (in this order, the verdict can no longer contradict the evidence).
                "properties": {
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["soutenue", "non_soutenue"]},
                },
                "required": ["claim", "evidence", "verdict"],
                "additionalProperties": False,
            },
        },
        "why_it_matters": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": WHY_CLASSES},
                "explanation": {"type": "string"},
            },
            "required": ["verdict", "explanation"],
            "additionalProperties": False,
        },
        "omissions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "why_it_matters", "omissions"],
    "additionalProperties": False,
}


def build_user_message(title: str, text: str, summary: str, why: str) -> str:
    # Article and summary are untrusted: escaping < > & stops them from faking our tags.
    esc = lambda s: html.escape(s, quote=False)
    return (
        f"<article>\nTitre : {esc(title)}\n\n{esc(text)}\n</article>\n\n"
        f"<resume>\n{esc(summary)}\n\nPourquoi c'est important : {esc(why)}\n</resume>"
    )


def fake_judgment(summary: str) -> dict:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s]
    return {
        "claims": [{"claim": s[:80], "verdict": "soutenue", "evidence": "[factice]"}
                   for s in sentences],
        "why_it_matters": {"verdict": "deduction_raisonnable", "explanation": "[factice]"},
        "omissions": [],
    }


def scores(judgment: dict) -> dict:
    claims = judgment["claims"]
    unsupported = sum(c["verdict"] != "soutenue" for c in claims)
    return {
        "claims": len(claims),
        "unsupported": unsupported,
        "supported_rate": round(1 - unsupported / len(claims), 3) if claims else None,
        "why_it_matters": judgment["why_it_matters"]["verdict"],
        "omissions": len(judgment["omissions"]),
    }


def to_judge(folder: Path) -> list[tuple[str, int, dict]]:
    """(config id, repeat, item) for every summary of the judged repetition, shuffled."""
    entries = []
    for path in sorted(folder.iterdir()):
        match = SUMMARY_FILE.fullmatch(path.name)
        if not match or int(match.group(1)) != REPEAT:
            continue
        result = json.loads(path.read_text())
        entries += [(result["config"]["id"], result["repeat"], item)
                    for item in result["items"] if item["summary"]]
    random.Random(SEED).shuffle(entries)
    return entries


def judgment_path(out_dir: Path, config_id: str, repeat: int, url: str) -> Path:
    return out_dir / f"{config_id}-{repeat}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.json"


def print_table(out_dir: Path) -> None:
    rows = defaultdict(list)
    for path in out_dir.glob("*.json"):
        record = json.loads(path.read_text())
        rows[record["config"]].append(record)
    print(f"{'config':<7}{'jugés':>6}{'affirm.':>9}{'non sout.':>11}{'taux sout.':>12}"
          f"{'omissions':>11}  pourquoi (texte / déduction / extérieur){'coût':>9}")
    for cid in sorted(rows):
        records = rows[cid]
        s = [r["scores"] for r in records]
        claims = sum(x["claims"] for x in s)
        unsupported = sum(x["unsupported"] for x in s)
        why = Counter(x["why_it_matters"] for x in s)
        cost = sum(r["llm_call"]["cost_usd"] for r in records)
        rate = f"{1 - unsupported / claims:.1%}" if claims else "-"
        print(f"{cid:<7}{len(records):>6}{claims:>9}{unsupported:>11}{rate:>12}"
              f"{sum(x['omissions'] for x in s):>11}  "
              f"{' / '.join(str(why[c]) for c in WHY_CLASSES):<40}{cost:>8.4f}$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge the bench summaries with an LLM.")
    parser.add_argument("--real", action="store_true", help="call the Anthropic API (paid)")
    parser.add_argument("--limit", type=int, help="judge only the first N summaries")
    parser.add_argument("--only", help="comma-separated config ids, e.g. S1,S5")
    parser.add_argument("--day", default="2026-11-15", help="frozen day (fixture name)")
    parser.add_argument("--force", action="store_true", help="judge again what is on disk")
    args = parser.parse_args()

    _, articles, _ = load_fixture(FIXTURES_DIR / f"{args.day}.json")
    text_by_url = {a.url: a.text for a in articles}
    entries = to_judge(RESULTS_DIR / args.day)  # the real summaries, even for the fake judge
    if args.only:
        entries = [e for e in entries if e[0] in args.only.split(",")]
    if args.limit:
        entries = entries[:args.limit]
    # One folder per prompt version: judgments of two versions are never mixed.
    out_dir = (RESULTS_DIR if args.real else FAKE_DIR) / args.day / "judge" / PROMPT_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = ClaudeLLM(model=JUDGE_MODEL, effort=JUDGE_EFFORT) if args.real else FakeLLM()
    system = (PROMPTS_DIR / f"judge_{PROMPT_VERSION}.md").read_text()
    print(f"judge: {'REAL (paid)' if args.real else 'fake'} mode, {len(entries)} summaries")

    def one(entry: tuple[str, int, dict]) -> float:
        config_id, repeat, item = entry
        path = judgment_path(out_dir, config_id, repeat, item["url"])
        if args.real and path.exists() and not args.force:
            return 0.0
        user = build_user_message(item["title"], text_by_url[item["url"]],
                                  item["summary"], item["why_it_matters"])
        # Broad except on purpose: one failed judgment must not stop the others. Nothing is
        # written, so the next run judges it again.
        try:
            data, call = llm.complete_json(
                task="judge", prompt_version=PROMPT_VERSION, system=system, user=user,
                schema=SCHEMA, max_tokens=MAX_TOKENS,
                fake_output=lambda: fake_judgment(item["summary"]),
            )
        except LLMOutputError as e:
            print(f"  error {config_id}-{repeat} [{item['title'][:40]}]: {e}")
            return e.call.cost_usd  # billed anyway
        except Exception as e:  # noqa: BLE001
            print(f"  error {config_id}-{repeat} [{item['title'][:40]}]: {type(e).__name__}")
            return 0.0
        record = {
            "config": config_id, "repeat": repeat, "url": item["url"], "title": item["title"],
            "judge": {"model": llm.model, "effort": getattr(llm, "effort", None),
                      "prompt": PROMPT_VERSION},
            "judgment": data, "scores": scores(data), "llm_call": asdict(call),
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return call.cost_usd

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        spent = sum(pool.map(one, entries))
    print_table(out_dir)
    print(f"spent this run: ${spent:.4f}   judgments: {out_dir}")


if __name__ == "__main__":
    main()
