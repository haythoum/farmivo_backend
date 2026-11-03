"""Date helpers and the gestation table."""

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
    """Today's date in the farms' time zone (FARMIVO_TIMEZONE, default Africa/Tunis), not the server's:
    a server in UTC would otherwise switch days an hour late. A function so tests can patch it."""
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from app.config import get_settings

    try:
        return datetime.now(ZoneInfo(get_settings().timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return date.today()


def parse_date(value: str | date | None) -> date | None:
    """Accept a date, an ISO string (first 10 characters used) or None."""
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
    """Mating date + typical gestation for the species, or None for unknown species."""
    days = GESTATION_DAYS.get(species or "")
    return mating + timedelta(days=days) if days else None
