from __future__ import annotations

from datetime import date, timedelta

# Typical gestation length in days, used to suggest an expected birth date.
GESTATION_DAYS: dict[str, int] = {
    "cattle": 283,
    "sheep": 147,
    "goat": 150,
    "pig": 114,
    "horse": 340,
    "rabbit": 31,
}


def today() -> date:
    return date.today()


def parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def age_parts(dob: date | None, until: date | None = None) -> tuple[int | None, int | None, str | None]:
    """Return (age_days, age_months, human label) for a date of birth."""
    if dob is None:
        return None, None, None
    end = until or today()
    if end < dob:
        return 0, 0, "0 days"
    days = (end - dob).days
    months = (end.year - dob.year) * 12 + (end.month - dob.month) - (1 if end.day < dob.day else 0)
    years, rem_months = divmod(months, 12)
    if years >= 1:
        label = f"{years}y {rem_months}m" if rem_months else f"{years}y"
    elif months >= 1:
        label = f"{months}m"
    else:
        label = f"{days}d"
    return days, months, label


def expected_birth(species: str | None, mating: date) -> date | None:
    days = GESTATION_DAYS.get(species or "")
    return mating + timedelta(days=days) if days else None
