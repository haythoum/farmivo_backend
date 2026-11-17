"""17 November 2026: the client's points (currency, purchases, newest first, barn capacity)."""
from __future__ import annotations

from tests.test_nov14 import add, expense, farm_client


def test_a_new_farm_gets_its_country_currency_or_tnd(make_client):
    from app.routers.members import default_currency

    assert default_currency("Tunisia") == "TND" and default_currency("تونس") == "TND"
    assert default_currency("Algérie") == "DZD" and default_currency(None) == "TND"


def test_animals_bought_cannot_be_typed_as_an_expense(make_client):
    c = farm_client(make_client)
    a = add(c, "S1")
    r = c.post("/v1/transactions", json={"type": "expense", "category": "purchase_animal", "amount": 500,
                                         "date": "2026-11-10", "animal_ids": [a["id"]]})
    assert r.status_code == 422 and "Add animal" in r.json["detail"]
    ar = c.post("/v1/transactions", headers={"Accept-Language": "ar"}, json={
        "type": "expense", "category": "purchase_animal", "amount": 500, "date": "2026-11-10"})
    assert "إضافة حيوان" in ar.json["detail"]
    feed = expense(c, 100, "feed")
    assert c.patch(f"/v1/transactions/{feed['id']}", json={"category": "purchase_animal"}).status_code == 422
    # the purchase booked with an animal is still there and can be edited
    bought = add(c, "S2", purchase_price=800)
    tx = [x for x in c.get("/v1/transactions").json if x["category"] == "purchase_animal"][0]
    assert tx["amount"] == 800 and bought
    assert c.patch(f"/v1/transactions/{tx['id']}", json={"description": "Market"}).status_code == 200


def test_entries_of_the_same_day_newest_first(make_client):
    c = farm_client(make_client)
    ids = [expense(c, n, "feed", date="2026-11-10")["id"] for n in (10, 20, 30)]
    listed = [x["id"] for x in c.get("/v1/transactions").json]
    assert listed[:3] == ids[::-1]


def test_reminder_when_a_barn_goes_over_its_capacity(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold", "capacity": 2}).json
    assert add(c, "S1", barn_id=fold["id"]).get("notice") is None
    assert add(c, "S2", barn_id=fold["id"]).get("notice") is None
    third = add(c, "S3", barn_id=fold["id"])
    assert third["notice"].startswith("Reminder: the barn “Fold” now has 3 animals for 2 places")
    assert c.get(f"/v1/animals/{third['id']}").json.get("notice") is None
    other = add(c, "S4")
    moved = c.patch(f"/v1/animals/{other['id']}", json={"barn_id": fold["id"]}, headers={"Accept-Language": "ar"}).json
    assert "4 حيوانات" in moved["notice"]
