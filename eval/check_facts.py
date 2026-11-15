"""Free fidelity check of the bench summaries: every number and every quote of a summary
must appear in the text the model was given. Exact rules, hence a script, not an LLM.

Usage: uv run python eval/check_facts.py [--day 2026-11-15]
Writes eval/results/<day>/checks.json and prints the flags to review by hand.

Accepted as faithful: "10 700" for "10.7k", "1,5 milliard" for "1.5bn", "93 %" for "93.4%"
(rounding), "3" for "three" (number words 1 to 20), and the title, which the model also sees.

Limits, by design (the LLM judge covers them): a flag is a lead, not a proof.
- Misses: a misinterpretation without any number ("threatens to resign" -> "resigned"); a
  small number in an article full of figures matches by chance.
- Quotes of an English article are translated, so they cannot be checked word for word.
"""

import argparse
import json
import re
from collections import defaultdict

from bench import FIXTURES_DIR, RESULTS_DIR, load_fixture

from digest.nodes.clean import shorten

RESULT_FILE = re.compile(r"S\d+-\d+\.json")  # summary results only
# "2 300", "20 000", "3,2", "1.5", "1,200,000", "2026": spaces only before groups of 3 digits,
# so "3, 4" stays two numbers. Then an optional scale: "10.7k", "98M", "40bn", "2 milliards".
NUMBER = re.compile(
    r"(\d+(?:[ \u00a0\u202f]\d{3}(?!\d)|[.,]\d+)*)"
    r"(?:\s?(k|K|M|bn|thousand|millions?|billions?|milliards?|mille)\b)?"
)
SCALES = {"k": 1e3, "K": 1e3, "thousand": 1e3, "mille": 1e3, "M": 1e6, "million": 1e6,
          "millions": 1e6, "bn": 1e9, "billion": 1e9, "billions": 1e9, "milliard": 1e9,
          "milliards": 1e9}
QUOTE = re.compile(r"«\s*(.+?)\s*»|“(.+?)”|\"(.+?)\"")
FALSE_FRIEND = re.compile(r"\b(billions?|trillions?)\b", re.IGNORECASE)  # FR billion = 10^12
NUMBER_WORDS = {
    word: value
    for value, words in enumerate([
        (), ("one", "un", "une"), ("two", "deux"), ("three", "trois"), ("four", "quatre"),
        ("five", "cinq"), ("six",), ("seven", "sept"), ("eight", "huit"), ("nine", "neuf"),
        ("ten", "dix"), ("eleven", "onze"), ("twelve", "douze"), ("thirteen", "treize"),
        ("fourteen", "quatorze"), ("fifteen", "quinze"), ("sixteen", "seize"),
        ("seventeen", "dix-sept"), ("eighteen", "dix-huit"), ("nineteen", "dix-neuf"),
        ("twenty", "vingt"),
    ])
    for word in words
}
EN_WORDS = {"the", "and", "of", "to", "is", "in", "that", "was", "for", "with"}
FR_WORDS = {"le", "la", "les", "des", "est", "et", "une", "du", "dans", "pour"}


def interpretations(token: str) -> set[float]:
    """Every value a written number can mean: "1,200" is 1200 in English, 1.2 in French."""
    s = re.sub(r"[ \u00a0\u202f]", "", token)
    seps = set(re.findall(r"[.,]", s))
    if not seps:
        return {float(s)}
    if len(seps) == 2:  # "1,200.5" or "1.200,5": the last separator is the decimal one
        decimal = s[max(s.rfind("."), s.rfind(","))]
        thousands = ({".", ","} - {decimal}).pop()
        return {float(s.replace(thousands, "").replace(decimal, "."))}
    sep = seps.pop()
    parts = s.split(sep)
    values = set()
    if all(len(p) == 3 for p in parts[1:]):  # could be thousands: "1,200" or "1.200.000"
        values.add(float("".join(parts)))
    if len(parts) == 2:  # could be a decimal: "3,2" or "1.200"
        values.add(float(f"{parts[0]}.{parts[1]}"))
    return values


def values(match: re.Match) -> set[float]:
    """The values of a number as written, and as scaled ("10.7k" is 10.7 and 10,700)."""
    base = interpretations(match.group(1))
    scale = SCALES.get(match.group(2) or "", 1)
    return base | {v * scale for v in base}


def is_supported(match: re.Match, source_values: set[float], source: str) -> bool:
    found = values(match)
    if not found:  # not a quantity, e.g. a version "0.4.0": look for it as written
        return match.group(1) in source
    # Rounding is faithful: "93 %" for "93.4%", "2,6" for "2.63".
    return any(abs(x - v) <= (0.5 if x.is_integer() else 0.05)
               for x in found for v in source_values)


def numbers_in(text: str) -> set[float]:
    found = set()
    for match in NUMBER.finditer(text):
        found |= values(match)
    for word in re.findall(r"[a-zà-ÿ-]+", text.casefold()):
        if word in NUMBER_WORDS:
            found.add(float(NUMBER_WORDS[word]))
    return found


def language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿ']+", text.casefold())
    return "fr" if sum(w in FR_WORDS for w in words) > sum(w in EN_WORDS for w in words) else "en"


def normalize(text: str) -> str:
    text = text.casefold().replace("’", "'").replace("\u00a0", " ").replace("\u202f", " ")
    return " ".join(re.sub(r"[^\w' ]", " ", text).split())


def context(text: str, start: int, end: int, width: int = 40) -> str:
    return " ".join(text[max(0, start - width):end + width].split())


def check(written: str, source: str) -> dict:
    """Flags for one piece of generated text (a summary or a "why it matters" sentence)."""
    source_numbers = numbers_in(source)
    numbers = list(NUMBER.finditer(written))
    unsupported_numbers = [
        {"value": m.group(), "context": context(written, m.start(), m.end())}
        for m in numbers
        if not is_supported(m, source_numbers, source)
    ]
    quotes, unsupported_quotes, translated = 0, [], 0
    source_fr, normalized_source = language(source) == "fr", normalize(source)
    for m in QUOTE.finditer(written):
        quote = next(g for g in m.groups() if g)
        quotes += 1
        if not source_fr:
            translated += 1  # English article: the quote is a translation
            continue
        # A quote cut with "…" must match piece by piece.
        pieces = [normalize(p) for p in re.split(r"…|\.\.\.", quote) if normalize(p)]
        if not all(p in normalized_source for p in pieces):
            unsupported_quotes.append(quote)
    return {
        "numbers": len(numbers),
        "unsupported_numbers": unsupported_numbers,
        "quotes": quotes,
        "unsupported_quotes": unsupported_quotes,
        "translated_quotes": translated,
        "false_friends": FALSE_FRIEND.findall(written),
    }


def seen_text(article_text: str, max_text: int) -> str:
    """The text the model was given (S4 saw the article cut at 6,000 characters)."""
    return shorten(article_text, max_text) if len(article_text) > max_text else article_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Check numbers and quotes of the summaries.")
    parser.add_argument("--day", default="2026-11-15", help="frozen day (fixture name)")
    args = parser.parse_args()

    _, articles, _ = load_fixture(FIXTURES_DIR / f"{args.day}.json")
    text_by_url = {a.url: a.text for a in articles}
    folder = RESULTS_DIR / args.day
    rows, totals = [], defaultdict(lambda: defaultdict(int))
    for path in sorted(p for p in folder.iterdir() if RESULT_FILE.fullmatch(p.name)):
        result = json.loads(path.read_text())
        config = result["config"]
        for item in result["items"]:
            if not item["summary"]:
                continue
            # What the model was given: the title, then the (possibly cut) text.
            source = item["title"] + "\n" + seen_text(text_by_url[item["url"]], config["max_text"])
            for field in ("summary", "why_it_matters"):
                flags = check(item[field], source)
                rows.append({"config": config["id"], "repeat": result["repeat"],
                             "url": item["url"], "title": item["title"], "field": field, **flags})
                t = totals[config["id"]]
                t["texts"] += 1
                t["numbers"] += flags["numbers"]
                t["unsupported_numbers"] += len(flags["unsupported_numbers"])
                t["texts_with_unsupported_number"] += bool(flags["unsupported_numbers"])
                t["quotes"] += flags["quotes"]
                t["unsupported_quotes"] += len(flags["unsupported_quotes"])
                t["translated_quotes"] += flags["translated_quotes"]
                t["false_friends"] += len(flags["false_friends"])

    out = folder / "checks.json"
    out.write_text(json.dumps({"totals": totals, "flags": [
        r for r in rows
        if r["unsupported_numbers"] or r["unsupported_quotes"] or r["false_friends"]
    ]}, ensure_ascii=False, indent=1))

    print(f"{'config':<7}{'textes':>7}{'nombres':>9}{'non trouvés':>13}{'citations':>11}"
          f"{'non trouvées':>14}{'traduites':>11}{'faux amis':>11}")
    for cid in sorted(totals):
        t = totals[cid]
        print(f"{cid:<7}{t['texts']:>7}{t['numbers']:>9}{t['unsupported_numbers']:>13}"
              f"{t['quotes']:>11}{t['unsupported_quotes']:>14}{t['translated_quotes']:>11}"
              f"{t['false_friends']:>11}")
    print("\nÀ revoir à la main (une alerte n'est pas une preuve) :")
    for r in rows:
        for n in r["unsupported_numbers"]:
            print(f"  {r['config']}-{r['repeat']} {r['field']:<15} nombre « {n['value']} » : …{n['context']}…"
                  f"  [{r['title'][:40]}]")
        for q in r["unsupported_quotes"]:
            print(f"  {r['config']}-{r['repeat']} {r['field']:<15} citation « {q[:80]} »  [{r['title'][:40]}]")
        for w in r["false_friends"]:
            print(f"  {r['config']}-{r['repeat']} {r['field']:<15} faux ami possible « {w} »  [{r['title'][:40]}]")
    print(f"\ndétail : {out}")


if __name__ == "__main__":
    main()
