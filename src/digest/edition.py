"""Edition date: the morning the journal is made for.

The cron runs in the evening (around 20:00 in Paris) so that the journal is on the Kindle on
waking, and GitHub can start a scheduled run hours late, sometimes after midnight. Hence the
rule: a run from noon on makes tomorrow's journal, a run before noon makes today's.
An exact rule: a script, no LLM.
"""

from datetime import date, datetime, timedelta

NOON = 12


def edition_date(now: datetime) -> date:
    """now: the time of the run, in Paris time."""
    return now.date() + timedelta(days=1) if now.hour >= NOON else now.date()
