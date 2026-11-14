"""Tests for the run report."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from digest import report
from digest.report import write_run_report

PARIS = ZoneInfo("Europe/Paris")
HAIKU = SimpleNamespace(model="claude-haiku-5-5", effort="medium")


def test_two_runs_on_the_same_day_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "RUNS_DIR", tmp_path)

    morning = write_run_report({}, 40.0, HAIKU, now=datetime(2026, 11, 15, 5, 31, tzinfo=PARIS))
    evening = write_run_report({}, 42.0, HAIKU, now=datetime(2026, 11, 15, 19, 2, tzinfo=PARIS))

    assert (morning.name, evening.name) == ("2026-11-15_0531.json", "2026-11-15_1902.json")
    first = json.loads(morning.read_text())
    assert first["totals"]["seconds"] == 40.0
    assert first["finished_at"] == "2026-11-15T05:31:00+01:00"


def test_fake_runs_go_to_the_ignored_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "FAKE_DIR", tmp_path)
    fake = SimpleNamespace(model="fake")

    path = write_run_report({}, 3.0, fake, now=datetime(2026, 11, 15, 21, 0, tzinfo=PARIS))

    assert path == tmp_path / "run-2026-11-15_2100-fake.json"
