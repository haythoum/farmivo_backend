"""scripts/delete_farm.py: the admin tool that deletes one farm and all its data, and the list of farm
collections it relies on."""
import pathlib
import re

from scripts import delete_farm as tool

from app.repository import farm_path
from app.services.account import FARM_COLLECTIONS

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}


def _setup(make_client):
    owner = make_client("owner1", name="Owner")
    assert owner.post("/v1/farms", json=FARM).status_code in (200, 201)
    farm_id = owner.get("/v1/farm").json["id"]
    shed = owner.post("/v1/barns", json={"name": "Cow shed", "species": "cattle"}).json
    cow = owner.post("/v1/animals", json={"ear_tag": "001", "species": "cattle", "sex": "female",
                                          "barn_id": shed["id"]}).json
    owner.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD", "date_given": "2026-11-01",
                                         "next_due_date": "2026-12-01"})
    return owner, farm_id


def test_every_farm_collection_used_in_the_code_is_deleted():
    used = set()
    for f in pathlib.Path("app").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        used |= set(re.findall(r'path_of\(ctx, "([a-z_]+)"\)', text))
        used |= set(re.findall(r'farm_path\([^,()]+, "([a-z_]+)"\)', text))
    assert used, "the scan found nothing"
    assert used <= set(FARM_COLLECTIONS), f"missing in FARM_COLLECTIONS: {sorted(used - set(FARM_COLLECTIONS))}"


def test_list_find_dry_run_and_confirmed_delete(make_client, repo, photo_store):
    owner, farm_id = _setup(make_client)
    out = []
    assert tool.run(repo, photo_store, [], say=out.append) == 0
    assert any(farm_id in line and "Green Valley Farm" in line for line in out)
    out.clear()
    assert tool.run(repo, photo_store, ["--find", "nothing-like-this"], say=out.append) == 0
    assert out[-1].startswith("0 farm")

    out.clear()
    assert tool.run(repo, photo_store, [farm_id, "--dry-run"], say=out.append) == 0
    assert any("barns" in line for line in out) and any("animals" in line for line in out)
    assert repo.get("farms", farm_id)

    # wrong name typed: nothing deleted
    assert tool.run(repo, photo_store, [farm_id], ask=lambda _: "green valley", say=out.append) == 1
    assert repo.get("farms", farm_id)

    assert tool.run(repo, photo_store, [farm_id], ask=lambda _: "Green Valley Farm", say=out.append) == 0
    assert repo.get("farms", farm_id) is None
    for c in FARM_COLLECTIONS:
        assert repo.list(farm_path(farm_id, c)) == [], c
    # the owner keeps the sign-in and simply has no farm: the app offers to create or join one
    assert owner.get("/v1/farm").status_code in (403, 404, 409)


def test_unknown_farm(repo, photo_store):
    out = []
    assert tool.run(repo, photo_store, ["nope"], say=out.append) == 1
