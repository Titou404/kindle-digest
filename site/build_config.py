"""Build the "config" page: inject eval/results/<day>/summary.json into the template.

Usage (from the project root): uv run python site/build_config.py [2026-11-15]
Writes config.html at the root of the repository, next to index.html: GitHub Pages serves
the root, so that the pages can read runs/ with a relative path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
day = sys.argv[1] if len(sys.argv) > 1 else "2026-11-15"
data = (ROOT / "eval" / "results" / day / "summary.json").read_text()
# "</" would close the <script> tag that holds the data; "<\/" is the same string in JSON.
page = (Path(__file__).parent / "config.template.html").read_text()
(ROOT / "config.html").write_text(page.replace("__BENCH_DATA__", data.replace("</", "<\\/")))
print(ROOT / "config.html")
