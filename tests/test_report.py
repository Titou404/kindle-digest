"""Tests for the run report."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from digest import report
from digest.report import write_run_report

PARIS = ZoneInfo("Europe/Paris")
LLMS = {"rank": SimpleNamespace(model="claude-haiku-5-5", effort="low"),
        "summarize": SimpleNamespace(model="claude-haiku-5-5", effort="medium")}


def test_two_runs_on_the_same_day_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "RUNS_DIR", tmp_path)

    morning = write_run_report({}, 40.0, LLMS, now=datetime(2026, 11, 15, 5, 31, tzinfo=PARIS))
    evening = write_run_report({}, 42.0, LLMS, now=datetime(2026, 11, 15, 19, 2, tzinfo=PARIS))

    assert (morning.name, evening.name) == ("2026-11-15_0531.json", "2026-11-15_1902.json")
    first = json.loads(morning.read_text())
    assert first["totals"]["seconds"] == 40.0
    assert first["finished_at"] == "2026-11-15T05:31:00+01:00"


def test_the_report_records_the_effort_of_each_task(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "RUNS_DIR", tmp_path)

    path = write_run_report({}, 40.0, LLMS, now=datetime(2026, 11, 16, 5, 31, tzinfo=PARIS))

    config = json.loads(path.read_text())["config"]
    assert config["effort"] == {"rank": "low", "summarize": "medium"}
    assert config["prompts"]["summarize"] == "v2"


def test_the_report_gives_the_morning_the_journal_is_made_for(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "RUNS_DIR", tmp_path)

    path = write_run_report({}, 40.0, LLMS, now=datetime(2026, 11, 16, 20, 17, tzinfo=PARIS))

    written = json.loads(path.read_text())
    assert (written["date"], written["edition"]) == ("2026-11-16", "2026-11-17")
    assert path.name == "2026-11-16_2017.json"  # the file keeps the time of the run


def test_the_report_says_who_started_the_run_and_the_index_follows(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "RUNS_DIR", tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    write_run_report({}, 40.0, LLMS, now=datetime(2026, 11, 16, 5, 31, tzinfo=PARIS))
    monkeypatch.delenv("GITHUB_EVENT_NAME")
    write_run_report({}, 40.0, LLMS, now=datetime(2026, 11, 16, 20, 0, tzinfo=PARIS))

    index = json.loads((tmp_path / "index.json").read_text())
    assert index["runs"] == [  # newest first
        {"file": "2026-11-16_2000.json", "finished_at": "2026-11-16T20:00:00+01:00", "trigger": "local"},
        {"file": "2026-11-16_0531.json", "finished_at": "2026-11-16T05:31:00+01:00", "trigger": "schedule"},
    ]


def test_old_reports_get_their_time_from_the_name_and_their_trigger_from_the_table(tmp_path):
    (tmp_path / "2026-11-15_1311.json").write_text("{}")  # an old report: no trigger, no finished_at

    [run] = json.loads(report.write_runs_index(tmp_path).read_text())["runs"]

    assert run == {"file": "2026-11-15_1311.json", "finished_at": "2026-11-15T13:11:00+01:00",
                   "trigger": "schedule"}


def test_fake_runs_go_to_the_ignored_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "FAKE_DIR", tmp_path)
    fake = {"rank": SimpleNamespace(model="fake"), "summarize": SimpleNamespace(model="fake")}

    path = write_run_report({}, 3.0, fake, now=datetime(2026, 11, 15, 21, 0, tzinfo=PARIS))

    assert path == tmp_path / "run-2026-11-15_2100-fake.json"
