"""Freeze a day for the evaluation bench: today's candidates, and the full text of the
articles to summarize, in eval/fixtures/AAAA-MM-JJ.json (ignored by git: press articles).

Usage: uv run python eval/freeze_day.py --scores runs/2026-11-15_1220.json

No paid call. The articles to summarize are the ones production would pick: the scores
of a real run (--scores) are copied onto today's candidates by title, then select's own
rules apply. Run it once: it queries every source, and Reddit limits anonymous requests.
"""

import argparse
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from bench import FIXTURES_DIR, save_fixture

from digest.nodes.clean import clean_articles, title_key
from digest.nodes.collect import collect
from digest.nodes.fetch_text import fetch_text
from digest.nodes.select import QUOTAS, select_articles
from digest.sources import load_sources

SPARE = 5  # articles tried per section, to still have 3 with a readable text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scores", type=Path, required=True, help="a real run report")
    args = parser.parse_args()
    now = datetime.now(UTC)

    # 1. Same as the first two nodes of the graph: collect every source, then clean.
    collected, errors = [], []
    for source in load_sources():
        out = collect({"source": source})  # waits delay_s first (Reddit)
        collected += out["collected"]
        errors += out["errors"]
    candidates, clean_counts = clean_articles(collected, now=now)

    # 2. Scores of the real run, matched by title (no LLM call).
    report = json.loads(args.scores.read_text())
    by_title = {title_key(c["title"]): c for c in report["candidates"]}
    scored = []
    for article in candidates:
        hit = by_title.get(title_key(article.title))
        scored.append(replace(article, score=hit["score"], topic=hit["topic"]) if hit else article)
    matched = sum(a.score is not None for a in scored)

    # 3. Select's rules with larger quotas, then the first 3 readable texts per section.
    ordered, _ = select_articles(scored, quotas={section: SPARE for section in QUOTAS})
    fetched = fetch_text({"selected": [a for a in ordered if not a.raw]})
    errors += fetched["errors"]
    articles, kept = [], Counter()
    for article in fetched["selected"]:
        if article.text and kept[article.section] < QUOTAS[article.section]:
            articles.append(article)
            kept[article.section] += 1

    path = FIXTURES_DIR / f"{now:%Y-%m-%d}.json"
    meta = {
        "frozen_at": now.isoformat(timespec="seconds"),
        "scores_from": str(args.scores),
        "collected": len(collected),
        "candidates": len(candidates),
        "matched_scores": matched,
        "clean": clean_counts,
        "errors": [f"{e.source}: {e.error}" for e in errors],
    }
    save_fixture(path, candidates, articles, meta)

    print(f"{len(collected)} collected -> {len(candidates)} candidates "
          f"({matched} with a score from {args.scores})")
    print(f"{len(articles)} articles to summarize: {dict(kept)}")
    for article in articles:
        print(f"  {article.section:<7}{article.score!s:>3}  {len(article.text):>6} chars  "
              f"{article.title[:70]}")
    for e in errors:
        print(f"  error: {e.source}: {e.error}")
    print(f"fixture: {path}")


if __name__ == "__main__":
    main()
