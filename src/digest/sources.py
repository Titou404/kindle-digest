"""Load the list of sources from config/sources.toml."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from digest.paths import CONFIG_DIR

DEFAULT_PATH = CONFIG_DIR / "sources.toml"
KINDS = {"hn", "feed"}
SECTIONS = {"data", "monde", "eco", "france"}


@dataclass(frozen=True)
class Source:
    name: str
    kind: str  # "hn" (Hacker News JSON API) or "feed" (RSS / Atom)
    section: str
    url: str


def load_sources(path: Path = DEFAULT_PATH) -> list[Source]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    sources = [Source(**entry) for entry in data["sources"]]

    for source in sources:
        if source.kind not in KINDS:
            raise ValueError(f"{source.name}: unknown kind {source.kind!r}")
        if source.section not in SECTIONS:
            raise ValueError(f"{source.name}: unknown section {source.section!r}")
    names = [source.name for source in sources]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate source names: {duplicates}")

    return sources
