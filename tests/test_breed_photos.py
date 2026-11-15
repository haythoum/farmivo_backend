"""Real breed photos: the catalog's photo URLs, the public photo route and the download script."""
from __future__ import annotations

import json

import pytest

from app import breed_photos

JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 10
PNG = b"\x89PNG\r\n" + b"drawing"


@pytest.fixture
def photos(tmp_path, monkeypatch):
    monkeypatch.setattr(breed_photos, "photos_dir", lambda: tmp_path)
    return tmp_path


def test_slug():
    assert breed_photos.slug("Brune de l'Atlas") == "brune-de-l-atlas"
    assert breed_photos.slug("Piétrain") == "pietrain"
    assert breed_photos.slug("Ross 308 (broiler)") == "ross-308-broiler"


def test_every_source_is_a_listed_breed():
    from app.breeds import BREEDS
    for species, sources in breed_photos.SOURCES.items():
        names = {b[0] for b in BREEDS[species]}
        assert set(sources) <= names, species
    assert set(breed_photos.SPECIES_SOURCES) <= set(BREEDS)


def test_catalog_gives_breed_photo_then_species_photo_then_none(client, photos):
    (photos / "sheep").mkdir()
    (photos / "sheep" / "barbarine.jpg").write_bytes(JPEG)
    (photos / "sheep" / "_species.jpg").write_bytes(JPEG)
    (photos / "credits.json").write_text(json.dumps({"sheep/barbarine": {"text": "A. Author · CC BY-SA 4.0 · Wikimedia Commons"}}))
    sheep = {b["name"]: b["photo"] for b in client.get("/v1/breeds").json["sheep"]}
    assert sheep["Barbarine"] == {"url": "http://localhost/v1/breeds/photo/sheep/barbarine.jpg",
                                  "credit": "A. Author · CC BY-SA 4.0 · Wikimedia Commons", "generic": False}
    assert sheep["Crossbred"] == {"url": "http://localhost/v1/breeds/photo/sheep/_species.jpg", "credit": None,
                                  "generic": True}
    cattle = client.get("/v1/breeds").json["cattle"]
    assert all(b["photo"] is None for b in cattle)


def test_photo_route_is_public_and_guarded(client, photos):
    (photos / "goat").mkdir()
    (photos / "goat" / "boer.jpg").write_bytes(JPEG)
    client.environ_base.pop("HTTP_AUTHORIZATION", None)
    r = client.get("/v1/breeds/photo/goat/boer.jpg", headers={"Authorization": ""})
    assert r.status_code == 200 and r.data == JPEG and r.mimetype == "image/jpeg"
    assert "max-age" in r.headers.get("Cache-Control", "")
    assert client.get("/v1/breeds/photo/goat/saanen.jpg").status_code == 404
    assert client.get("/v1/breeds/photo/goat/..%2Fcredits.json").status_code == 404
    assert client.get("/v1/breeds/photo/goat/boer.png").status_code == 404


def _fake_wikipedia(pages: dict[str, tuple[str, bytes]]):
    """fetch() answering the Wikipedia API: pages = {title: (file name, image bytes)}."""
    from urllib.parse import parse_qs, urlsplit
    calls = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if url.startswith("https://upload/"):
            return pages[url.removeprefix("https://upload/")][1]
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        title = q["titles"]
        if q["prop"] == "pageimages":
            if title not in pages:
                return json.dumps({"query": {"pages": [{"title": title, "missing": True}]}}).encode()
            return json.dumps({"query": {"pages": [{"title": title, "pageimage": pages[title][0],
                                                     "thumbnail": {"source": f"https://upload/{title}"}}]}}).encode()
        return json.dumps({"query": {"pages": [{"imageinfo": [{"descriptionurl": "https://commons/x", "extmetadata": {
            "Artist": {"value": '<a href="x">Jane &amp; Co</a>'}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}]}}).encode()
    return fetch, calls


def test_script_saves_jpeg_photos_with_credits_and_keeps_own_photos(tmp_path):
    from scripts.fetch_breed_photos import run
    fetch, calls = _fake_wikipedia({
        "Sheep": ("Sheep.jpg", JPEG),
        "Merino": ("Merino.jpg", JPEG),
        "Lacaune sheep": ("Lacaune map.png", PNG),  # a drawing, not a photo: skipped
    })
    (tmp_path / "sheep").mkdir()
    (tmp_path / "sheep" / "texel.jpg").write_bytes(b"\xff\xd8 my own photo")
    report = run(fetch, tmp_path, only="sheep", pause=0)
    assert (tmp_path / "sheep" / "merino.jpg").read_bytes() == JPEG
    assert (tmp_path / "sheep" / "_species.jpg").is_file()
    assert not (tmp_path / "sheep" / "lacaune.jpg").exists()
    assert (tmp_path / "sheep" / "texel.jpg").read_bytes() == b"\xff\xd8 my own photo"
    credits = json.loads((tmp_path / "credits.json").read_text())
    assert credits["sheep/merino"]["text"] == "Jane & Co · CC BY-SA 4.0 · Wikimedia Commons"
    assert "sheep/texel" not in credits
    assert "sheep/merino.jpg" in report["own"] and "sheep/texel.jpg" in report["own"]
    assert "sheep/lacaune.jpg" in report["species"] and "sheep/crossbred.jpg" in report["species"]
    # Run again: nothing is downloaded again; --force downloads only what it downloaded, never the own photo.
    calls.clear()
    run(fetch, tmp_path, only="sheep", pause=0)
    assert not any(c.startswith("https://upload/") and "Merino" in c for c in calls)
    run(fetch, tmp_path, only="sheep", force=True, pause=0)
    assert any(c == "https://upload/Merino" for c in calls)
    assert (tmp_path / "sheep" / "texel.jpg").read_bytes() == b"\xff\xd8 my own photo"
