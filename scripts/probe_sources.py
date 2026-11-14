"""Check every candidate source once and print a summary table.

Usage: uv run python scripts/probe_sources.py
"""

import time
from datetime import UTC, datetime, timedelta

from digest.collectors import FETCHERS, describe_error, make_client
from digest.extract import extract_text
from digest.sources import load_sources

SAMPLES = 3  # articles per source whose full text we try to extract
MIN_TEXT = 1000  # fewer characters than this: probably a teaser (paywall)
ROW = "{:<24}{:<10}{:>9}{:>6}{:>7}{:>9}  {:<22}{:>7}"


def percent(part: int, total: int) -> str:
    return f"{100 * part // total}%" if total else "-"


def main() -> None:
    since = datetime.now(UTC) - timedelta(hours=24)
    header = ROW.format("source", "status", "articles", "24h", "dated", "snippet", "text (chars)", "time")
    print(header)
    print("-" * len(header))
    endings = []  # (source, length, last characters) of each extracted text

    with make_client() as client:
        for source in load_sources():
            start = time.perf_counter()
            # Broad except on purpose: any failure is reported in the table,
            # and one broken source must not stop the probe.
            try:
                articles = FETCHERS[source.kind](client, source)
            except Exception as e:  # noqa: BLE001
                elapsed = f"{time.perf_counter() - start:.1f}s"
                print(ROW.format(source.name, describe_error(e), "-", "-", "-", "-", "-", elapsed))
                continue
            elapsed = f"{time.perf_counter() - start:.1f}s"

            dated = [a for a in articles if a.published]
            recent = sum(a.published >= since for a in dated)
            with_snippet = sum(bool(a.snippet) for a in articles)

            samples = articles[:SAMPLES]
            lengths = []
            for article in samples:
                text = article.text  # already there if the feed includes the full text
                if not text:
                    try:
                        text = extract_text(client, article.url)
                    except Exception as e:  # noqa: BLE001
                        lengths.append(describe_error(e).removeprefix("HTTP "))
                        continue
                lengths.append(f"{len(text)}{'*' if len(text) < MIN_TEXT else ''}")
                endings.append((source.name, len(text), " ".join(text[-70:].split())))
            from_feed = " (feed)" if any(a.text for a in samples) else ""

            print(ROW.format(
                source.name, "OK", len(articles), recent,
                percent(len(dated), len(articles)), percent(with_snippet, len(articles)),
                " ".join(lengths) + from_feed, elapsed,
            ))

    print(f"\n* fewer than {MIN_TEXT} characters: probably a teaser or a paywall.")
    print("\nEnd of each extracted text (a paywall often ends with a subscription message):")
    for name, length, ending in endings:
        print(f"  {name:<24}{length:>6}  …{ending}")


if __name__ == "__main__":
    main()
