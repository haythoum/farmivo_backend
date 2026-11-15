"""Real photos of the breeds, shown in the apps' breed list (GET /v1/breeds gives each breed's ``photo`` URL).

The photos are files on the server, in ``FARMIVO_BREED_PHOTOS_DIR`` (default ``data/breed_photos`` in the project
folder), one per breed: ``<species>/<slug>.jpg`` (``sheep/barbarine.jpg``), plus ``<species>/_species.jpg``, the
photo used for a breed that has none (crossbreds, local types, breeds without a free photo). They are served by
GET /v1/breeds/photo/<species>/<file> (public: no sign-in, so the apps' image loaders can fetch them).

``scripts/fetch_breed_photos.py`` downloads them once from Wikipedia / Wikimedia Commons (only freely licensed
photos) and writes ``credits.json`` (author and licence of each photo, shown under the photo as the licences
require). A farmer's own photo can replace any of them: copy it as ``<species>/<slug>.jpg``; the script never
overwrites a file that is already there (unless run with --force) and a photo without credits shows no credit line.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SPECIES_FILE = "_species"

# Where to look for a breed's photo: Wikipedia articles (language, title), the first one with a free lead photo
# wins. Breeds not listed here (crossbreds, local types) and breeds where no article has a photo use the species'
# photo.
SOURCES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "cattle": {
        "Holstein": [("en", "Holstein Friesian cattle")],
        "Montbéliarde": [("en", "Montbéliarde"), ("fr", "Montbéliarde")],
        "Brown Swiss": [("en", "Brown Swiss cattle")],
        "Tarentaise": [("en", "Tarentaise cattle"), ("fr", "Tarine")],
        "Simmental": [("en", "Simmental cattle")],
        "Brune de l'Atlas": [("fr", "Brune de l'Atlas"), ("en", "Brune de l'Atlas")],
        "Blonde du Cap Bon": [("fr", "Blonde du cap Bon")],
        "Charolais": [("en", "Charolais cattle")],
        "Limousin": [("en", "Limousin cattle")],
        "Blonde d'Aquitaine": [("en", "Blonde d'Aquitaine")],
        "Normande": [("en", "Normande cattle")],
        "Jersey": [("en", "Jersey cattle")],
    },
    "sheep": {
        "Barbarine": [("fr", "Barbarine (race ovine)"), ("fr", "Barbarine (mouton)"), ("en", "Barbarine sheep")],
        "Queue Fine de l'Ouest": [("fr", "Queue fine de l'Ouest"), ("en", "Queue Fine de l'Ouest")],
        "Noire de Thibar": [("fr", "Noire de Thibar"), ("en", "Noire de Thibar")],
        "Sicilo-Sarde": [("fr", "Sicilo-sarde"), ("en", "Sicilo-Sarde")],
        "D'man": [("fr", "D'man"), ("en", "D'man sheep")],
        "Ouled Djellal": [("fr", "Ouled Djellal (race ovine)"), ("en", "Ouled Djellal sheep"),
                          ("en", "Algerian Arab sheep")],
        "Merino": [("en", "Merino")],
        "Lacaune": [("en", "Lacaune sheep")],
        "Awassi": [("en", "Awassi")],
        "Assaf": [("en", "Assaf sheep")],
        "Texel": [("en", "Texel sheep")],
        "Suffolk": [("en", "Suffolk sheep")],
    },
    "goat": {
        "Alpine": [("en", "Alpine goat")],
        "Saanen": [("en", "Saanen goat")],
        "Damascus (Shami)": [("en", "Damascus goat")],
        "Maltese": [("en", "Maltese goat")],
        "Murciano-Granadina": [("en", "Murciano-Granadina")],
        "Boer": [("en", "Boer goat")],
        "Anglo-Nubian": [("en", "Anglo-Nubian goat")],
    },
    "horse": {
        "Arabian": [("en", "Arabian horse")],
        "Barb": [("en", "Barb horse")],
        "Arab-Barb": [("en", "Arab–Barb"), ("fr", "Arabe-barbe")],
        "Thoroughbred": [("en", "Thoroughbred")],
        "Andalusian": [("en", "Andalusian horse")],
        "Percheron": [("en", "Percheron")],
        "Pony": [("en", "Pony")],
    },
    "pig": {
        "Large White": [("en", "Large White pig")],
        "Landrace": [("en", "Landrace pig")],
        "Duroc": [("en", "Duroc pig")],
        "Piétrain": [("en", "Piétrain pig")],
        "Hampshire": [("en", "Hampshire pig")],
    },
    "dog": {
        "Sloughi": [("en", "Sloughi")],
        "German Shepherd": [("en", "German Shepherd")],
        "Belgian Malinois": [("en", "Malinois dog"), ("en", "Belgian Shepherd")],
        "Kangal": [("en", "Kangal Shepherd Dog")],
        "Border Collie": [("en", "Border Collie")],
        "Labrador": [("en", "Labrador Retriever")],
    },
    "cat": {
        "European": [("en", "European Shorthair")],
        "Siamese": [("en", "Siamese cat")],
        "Persian": [("en", "Persian cat")],
        "Maine Coon": [("en", "Maine Coon")],
    },
    "chicken": {
        "ISA Brown": [("en", "ISA Brown")],
        "Lohmann Brown": [("en", "Lohmann Brown"), ("de", "Lohmann Brown")],
        "Leghorn": [("en", "Leghorn chicken")],
        "Rhode Island Red": [("en", "Rhode Island Red")],
        "Sussex": [("en", "Sussex chicken")],
        "Ross 308 (broiler)": [("en", "Broiler")],
        "Cobb 500 (broiler)": [("en", "Broiler")],
    },
    "duck": {
        "Pekin": [("en", "American Pekin")],
        "Muscovy": [("en", "Muscovy duck")],
        "Mulard": [("en", "Mulard duck"), ("en", "Mulard")],
        "Khaki Campbell": [("en", "Khaki Campbell")],
    },
    "rabbit": {
        "New Zealand White": [("en", "New Zealand rabbit")],
        "Californian": [("en", "Californian rabbit")],
        "Flemish Giant": [("en", "Flemish Giant rabbit")],
        "Rex": [("en", "Rex rabbit")],
    },
}

# The species' photo (for crossbreds, local types and breeds without a photo of their own).
SPECIES_SOURCES: dict[str, list[tuple[str, str]]] = {
    "cattle": [("en", "Cattle")],
    "sheep": [("en", "Sheep")],
    "goat": [("en", "Goat")],
    "horse": [("en", "Horse")],
    "pig": [("en", "Domestic pig")],
    "dog": [("en", "Dog")],
    "cat": [("en", "Cat")],
    "chicken": [("en", "Chicken")],
    "duck": [("en", "Domestic duck")],
    "rabbit": [("en", "Domestic rabbit")],
}


def photos_dir() -> Path:
    """The folder of the photos (FARMIVO_BREED_PHOTOS_DIR, absolute or relative to the project folder)."""
    from app.config import get_settings

    folder = Path(get_settings().breed_photos_dir)
    return folder if folder.is_absolute() else PROJECT_DIR / folder


def slug(name: str) -> str:
    """'Brune de l'Atlas' -> 'brune-de-l-atlas', 'Piétrain' -> 'pietrain' (the photo's file name)."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "breed"


def _credits(folder: Path) -> dict:
    try:
        return json.loads((folder / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def credits() -> dict:
    """credits.json of the photo folder: {"sheep/barbarine": {"text": "Author · CC BY-SA 4.0 · Wikimedia Commons",
    ...}} ({} when there is none)."""
    return _credits(photos_dir())


def photo(species: str, name: str, base_url: str, known_credits: dict | None = None) -> dict | None:
    """{"url", "credit", "generic"} of a breed's photo (``generic``: the species' photo, the breed has none of its
    own), or None when there is no photo at all. ``base_url`` is the server's address as the app reached it;
    ``known_credits`` = credits() read once for a whole list."""
    folder = photos_dir()
    for file, generic in ((slug(name), False), (SPECIES_FILE, True)):
        if (folder / species / f"{file}.jpg").is_file():
            table = known_credits if known_credits is not None else _credits(folder)
            credit = table.get(f"{species}/{file}", {}).get("text")
            return {"url": f"{base_url.rstrip('/')}/v1/breeds/photo/{species}/{file}.jpg", "credit": credit,
                    "generic": generic}
    return None
