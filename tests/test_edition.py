"""Tests for the edition date: which morning a run makes the journal for."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from digest.edition import edition_date

PARIS = ZoneInfo("Europe/Paris")


def test_an_evening_run_makes_the_journal_of_the_next_morning():
    assert edition_date(datetime(2026, 11, 16, 20, 17, tzinfo=PARIS)) == date(2026, 11, 17)


def test_an_evening_run_started_after_midnight_still_makes_that_morning_s_journal():
    # Scheduled at 20:17 on the 16th, started 8 hours late by GitHub: same edition.
    assert edition_date(datetime(2026, 11, 17, 4, 20, tzinfo=PARIS)) == date(2026, 11, 17)


def test_the_edition_crosses_the_end_of_the_year():
    assert edition_date(datetime(2026, 12, 31, 20, 17, tzinfo=PARIS)) == date(2027, 1, 1)
