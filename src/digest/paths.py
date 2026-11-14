"""Project folders, found from this file so that commands work from any directory."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # src/digest/paths.py -> project root
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
