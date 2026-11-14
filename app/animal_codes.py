"""The farm number of an animal, given by the app: ``<species code>-<number>/<year>``, e.g. ``01-0007/26``.

- species code: two digits (01 sheep, 02 cattle, 03 goats … 99 other), the same in every language;
- number: 0001, 0002 … per farm, species and year, handed out by the server (two phones adding animals at the same
  moment never get the same number; numbers are never reused);
- year: the year of birth for an animal born on the farm, the year it arrived (was bought) for the others.

Every animal gets one (``farm_code``). When the ear tag is left empty, the ear tag *is* this number; when an official
national number is entered as the ear tag, the farm number stays next to it. Offspring are linked to their mother and
father by ``mother_id`` / ``father_id``, which is what family tracking uses.
"""
from __future__ import annotations

from datetime import date

from app.repository import Repository, farm_path
from app.utils import parse_date, today

SPECIES_CODES = {
    "sheep": "01", "cattle": "02", "goat": "03", "horse": "04", "chicken": "05", "duck": "06", "rabbit": "07",
    "pig": "08", "dog": "09", "cat": "10", "other": "99",
}


def code_year(animal: dict) -> int:
    """Birth year when born on the farm (if known), else the year it arrived on the farm."""
    born = parse_date(animal.get("date_of_birth")) if animal.get("origin") == "born_on_farm" else None
    arrived = parse_date(animal.get("date_added"))
    d: date = born or arrived or today()
    return d.year


def format_code(species: str, number: int, year: int) -> str:
    return f"{SPECIES_CODES.get(species, '99')}-{number:04d}/{year % 100:02d}"


def set_counter_at_least(repo: Repository, farm_id: str, species: str, year: int, value: int) -> None:
    """Used by the upgrade script after numbering existing animals."""
    path = farm_path(farm_id, "counters")
    key = f"{species}-{year}"
    doc = repo.get(path, key)
    if doc is None:
        repo.set(path, key, {"value": value})
    elif int(doc.get("value") or 0) < value:
        repo.update(path, key, {"value": value})


def new_code(repo: Repository, farm_id: str, animal: dict, taken=None) -> str:
    """A new farm number for ``animal`` (needs species, origin, date_of_birth, date_added). ``taken(code)`` tells
    whether that text is already some animal's ear tag (a hand-typed tag can look like a farm number)."""
    species = animal.get("species") or "other"
    year = code_year(animal)
    while True:
        code = format_code(species, repo.increment(farm_path(farm_id, "counters"), f"{species}-{year}"), year)
        if taken is None or not taken(code):
            return code
