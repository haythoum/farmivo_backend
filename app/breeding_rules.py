"""What is biologically possible when an animal is mated, carries and gives birth (checked by /v1/breedings).

Figures agreed with the farm (November 2026) for sheep, goats and cattle; the others follow veterinary references
(MSD Veterinary Manual "Approximate Gestation Periods" and "Features of the Reproductive Cycle"; Wikipedia "List of
mammalian gestation durations"), with a margin so that real early or late births are not refused:

| species | female mated from | male mated from | pregnancy lasts | most young at once |
|---------|-------------------|-----------------|-----------------|--------------------|
| sheep   | 8 months          | 4 years (farm)  | 135 days – 5 months 10 days | 5 |
| goat    | 8 months          | 4 years (farm)  | 135 days – 5 months 10 days | 5 |
| cattle  | 12 months         | 4 years (farm)  | 260 days – 9 months 10 days | 3 |
| horse   | 24 months         | 24 months       | 310 – 370 days  | 2  |
| pig     | 7 months          | 7 months        | 108 – 125 days  | 20 |
| rabbit  | 5 months          | 6 months        | 28 – 35 days    | 15 |
| dog     | 8 months          | 8 months        | 56 – 72 days    | 16 |
| cat     | 6 months          | 8 months        | 56 – 70 days    | 10 |

Chickens and ducks lay eggs: they are not mated in Farmivo. "other" has no limits.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

BIRDS = {"chicken", "duck"}

# A miscarriage is recorded when it is seen: today, or up to this many days ago.
MISCARRIAGE_MAX_DAYS_AGO = 14


@dataclass(frozen=True)
class Rule:
    female_min_months: int
    male_min_months: int
    gestation_min_days: int
    gestation_max_months: int  # the longest pregnancy = mating + months + days
    gestation_max_days: int
    litter_max: int


RULES: dict[str, Rule] = {
    "sheep": Rule(8, 48, 135, 5, 10, 5),
    "goat": Rule(8, 48, 135, 5, 10, 5),
    "cattle": Rule(12, 48, 260, 9, 10, 3),
    "horse": Rule(24, 24, 310, 0, 370, 2),
    "pig": Rule(7, 7, 108, 0, 125, 20),
    "rabbit": Rule(5, 6, 28, 0, 35, 15),
    "dog": Rule(8, 8, 56, 0, 72, 16),
    "cat": Rule(6, 8, 56, 0, 70, 10),
}


def add_months(d: date, months: int) -> date:
    """Same day ``months`` later (the last day of the month when it is shorter: 31 Jan + 1 month = 28/29 Feb)."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``."""
    return (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)


def latest_birth(species: str | None, mating: date) -> date | None:
    """The last day a birth from this mating is possible, or None without limits."""
    rule = RULES.get(species or "")
    if not rule:
        return None
    return add_months(mating, rule.gestation_max_months) + timedelta(days=rule.gestation_max_days)


def earliest_birth(species: str | None, mating: date) -> date | None:
    """The first day a birth from this mating is possible, or None without limits."""
    rule = RULES.get(species or "")
    return mating + timedelta(days=rule.gestation_min_days) if rule else None


def gestation_text(species: str | None) -> str:
    """'5 months 10 days' / '370 days': the longest pregnancy, for messages."""
    rule = RULES.get(species or "")
    if not rule:
        return ""
    if rule.gestation_max_months:
        return f"{rule.gestation_max_months} months {rule.gestation_max_days} days"
    return f"{rule.gestation_max_days} days"


def age_text(months: int) -> str:
    """'8 months' / '4 years' / '1 year'."""
    if months % 12 == 0:
        years = months // 12
        return "1 year" if years == 1 else f"{years} years"
    return f"{months} months"
