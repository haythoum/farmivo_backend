"""Download the real breed photos shown in the apps' breed list (app/breed_photos.py). Run once on the server:

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.fetch_breed_photos

For each breed it reads the Wikipedia article(s) listed in app/breed_photos.py SOURCES, takes the article's lead
photo (Wikipedia only offers freely licensed ones there), keeps it only if it is a JPEG photo (not a drawing, map
or logo), and saves a 480-pixel copy as data/breed_photos/<species>/<breed>.jpg with its author and licence in
credits.json. Each species also gets a general photo (_species.jpg) for crossbreds, local types and breeds without
a photo. At the end it prints which breeds got their own photo and which use the species' photo.

Files already there are kept (your own photos too): run again any time; --force downloads again the photos it
downloaded before (never a photo you put there yourself). --species sheep limits it to one species.
Needs internet access from the server (wikipedia.org and upload.wikimedia.org).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from app.breed_photos import SOURCES, SPECIES_FILE, SPECIES_SOURCES, photos_dir, slug
from app.breeds import BREEDS

USER_AGENT = "FarmivoBreedPhotos/1.0 (https://quadralens.tn; contact@quadralens.tn)"
WIDTH = 480

Fetch = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    """GET with the User-Agent Wikimedia asks for."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def api(fetch: Fetch, lang: str, **params: str) -> dict:
    query = {"action": "query", "format": "json", "formatversion": "2", **params}
    return json.loads(fetch(f"https://{lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(query)}"))


def lead_photo(fetch: Fetch, lang: str, title: str) -> tuple[str, str] | None:
    """(file name, thumbnail URL) of the article's free lead image, or None (no article, no image)."""
    data = api(fetch, lang, titles=title, redirects="1", prop="pageimages", piprop="thumbnail|name",
               pithumbsize=str(WIDTH))
    for page in data.get("query", {}).get("pages", []):
        if page.get("missing") or "pageimage" not in page or "thumbnail" not in page:
            continue
        return page["pageimage"], page["thumbnail"]["source"]
    return None


def credit(fetch: Fetch, lang: str, file: str) -> dict:
    """{"text": "Author · CC BY-SA 4.0 · Wikimedia Commons", "author", "license", "source"} of an image."""
    data = api(fetch, lang, titles=f"File:{file}", prop="imageinfo", iiprop="extmetadata|url")
    info = {}
    for page in data.get("query", {}).get("pages", []):
        if page.get("imageinfo"):
            info = page["imageinfo"][0]
    meta = info.get("extmetadata", {})
    author = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).strip()
    author = re.sub(r"\s+", " ", author)[:80] or "Unknown author"
    license_name = meta.get("LicenseShortName", {}).get("value", "").strip() or "free licence"
    return {"text": f"{author} · {license_name} · Wikimedia Commons", "author": author, "license": license_name,
            "source": info.get("descriptionurl", "")}


def fetch_one(fetch: Fetch, candidates: list[tuple[str, str]]) -> tuple[bytes, dict] | None:
    """The first candidate article's photo as (JPEG bytes, credit), or None."""
    for lang, title in candidates:
        try:
            found = lead_photo(fetch, lang, title)
            if not found:
                continue
            file, url = found
            data = fetch(url)
            if not data.startswith(b"\xff\xd8"):  # a JPEG photo, not a PNG/SVG drawing, map or logo
                continue
            return data, {**credit(fetch, lang, file), "article": f"{lang}:{title}"}
        except (OSError, ValueError, KeyError) as e:  # network trouble or an odd answer: try the next one
            print(f"  ! {lang}:{title}: {e}", file=sys.stderr)
    return None


def run(fetch: Fetch, folder: Path, force: bool = False, only: str | None = None,
        pause: float = 0.5) -> dict[str, list[str]]:
    """Downloads the missing photos; returns {"own": [...], "species": [...], "none": [...]} (photo files, "sheep/barbarine.jpg")."""
    credits_file = folder / "credits.json"
    try:
        credits = json.loads(credits_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        credits = {}
    report: dict[str, list[str]] = {"own": [], "species": [], "none": []}

    def get(species: str, file: str, candidates: list[tuple[str, str]]) -> bool:
        target = folder / species / f"{file}.jpg"
        key = f"{species}/{file}"
        # A file put there by hand (no credits entry) is never replaced; a downloaded one only with --force.
        if target.is_file() and (not force or key not in credits):
            return True
        if not candidates:
            return False
        got = fetch_one(fetch, candidates)
        time.sleep(pause)  # be gentle with Wikimedia
        if not got:
            return target.is_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(got[0])
        credits[key] = got[1]
        credits_file.write_text(json.dumps(credits, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"  saved {key}.jpg  ({got[1]['article']})")
        return True

    for species, breeds in BREEDS.items():
        if only and species != only:
            continue
        has_species_photo = get(species, SPECIES_FILE, SPECIES_SOURCES.get(species, []))
        for breed in breeds:
            name = breed[0]
            file = f"{species}/{slug(name)}.jpg"
            if get(species, slug(name), SOURCES.get(species, {}).get(name, [])):
                report["own"].append(file)
            elif has_species_photo:
                report["species"].append(file)
            else:
                report["none"].append(file)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="download again the photos downloaded before")
    parser.add_argument("--species", help="only this species (sheep, cattle, goat ...)")
    args = parser.parse_args()
    folder = photos_dir()
    print(f"breed photos folder: {folder}")
    report = run(http_get, folder, force=args.force, only=args.species)
    print(f"\nbreeds with their own photo ({len(report['own'])}): {', '.join(report['own'])}")
    print(f"\nbreeds showing the species' photo ({len(report['species'])}): {', '.join(report['species'])}")
    if report["none"]:
        print(f"\nbreeds without any photo ({len(report['none'])}): {', '.join(report['none'])}")
    print(f"\nTo use your own photo for a breed, copy a JPEG into {folder} under the file name listed above "
          "(e.g. sheep/barbarine.jpg).")


if __name__ == "__main__":
    main()
