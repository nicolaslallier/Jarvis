"""Recurrence-rule parsing for recurring tasks.

Deliberately hand-rolled and minimal, matching this repo's existing bias
toward not pulling in a dependency (e.g. python-dateutil) for something this
small — see ingest/app/chunking.py's "naive, deliberately minimal" fixed-size
chunker for the same precedent. Supports exactly four rule shapes today:
"daily", "weekly", "monthly", and "every N days". Anything else is a clear
Pydantic-adjacent ValueError, not a silent no-op.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_EVERY_N_DAYS_RE = re.compile(r"^every (\d+) days$")


def _add_months(anchor: datetime, months: int) -> datetime:
    """Calendar-aware month arithmetic: Jan 31 + 1 month clamps to Feb 28/29
    rather than overflowing into March, the same "clamp to the shorter
    month's last day" behavior most calendar apps use. Built on stdlib
    `calendar.monthrange` only — no new dependency."""
    total_month_index = anchor.month - 1 + months
    year = anchor.year + total_month_index // 12
    month = total_month_index % 12 + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    day = min(anchor.day, last_day_of_month)
    return anchor.replace(year=year, month=month, day=day)


@dataclass(frozen=True)
class Recurrence:
    """Computes the next occurrence from a given anchor datetime.

    `kind` is one of "daily", "weekly", "monthly", "every_n_days"; `n` is
    only meaningful for "every_n_days" (day count) — kept as a plain
    dataclass rather than a class hierarchy since there's only one operation
    (`next_after`) and no other behavior that varies per kind.
    """

    kind: str
    n: int = 1

    def next_after(self, anchor: datetime) -> datetime:
        if self.kind == "daily":
            return anchor + timedelta(days=1)
        if self.kind == "weekly":
            return anchor + timedelta(days=7)
        if self.kind == "monthly":
            return _add_months(anchor, 1)
        if self.kind == "every_n_days":
            return anchor + timedelta(days=self.n)
        raise ValueError(f"unhandled recurrence kind: {self.kind!r}")


def parse_recurrence(rule: str) -> Recurrence:
    """Parses a recurrence-rule string into a `Recurrence`.

    Accepts "daily", "weekly", "monthly", or "every N days" (N a positive
    integer). Raises ValueError with a clear message on anything else, so a
    typo'd rule fails loudly at task-creation time (see schemas.py's
    validation) rather than silently never regenerating.
    """
    normalized = rule.strip().lower()
    if normalized == "daily":
        return Recurrence(kind="daily")
    if normalized == "weekly":
        return Recurrence(kind="weekly")
    if normalized == "monthly":
        return Recurrence(kind="monthly")
    match = _EVERY_N_DAYS_RE.match(normalized)
    if match:
        n = int(match.group(1))
        if n <= 0:
            raise ValueError(f"invalid recurrence rule {rule!r}: N must be positive")
        return Recurrence(kind="every_n_days", n=n)
    raise ValueError(
        f"unrecognized recurrence rule {rule!r}: expected 'daily', 'weekly', "
        "'monthly', or 'every N days'"
    )
