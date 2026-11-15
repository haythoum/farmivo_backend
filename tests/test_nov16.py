"""16 November 2026: animals sold together in one entry leave the farm with it; the balance sheet lists every sale
with each animal's average price, cost and result."""
from __future__ import annotations

from tests.test_nov14 import add, expense, farm_client, status


def sale(c, amount, animals, **kw):
    return c.post("/v1/transactions", json={"type": "income", "category": "animal_sale", "amount": amount,
                                            "date": "2026-11-10", "animal_ids": [a["id"] for a in animals], **kw})


def get(c, a):
    return c.get(f"/v1/animals/{a['id']}").json


def test_a_bulk_sale_sells_its_animals_at_the_average_price(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a = add(c, "S1", barn_id=fold["id"], purchase_price=600)
    b = add(c, "S2", barn_id=fold["id"], purchase_price=400)
    keep = add(c, "S3", barn_id=fold["id"], purchase_price=500)
    expense(c, 300, "veterinary", animal_ids=[a["id"], b["id"], keep["id"]])  # 100 each
    r = sale(c, 1680, [a, b], description="Sale to the butcher")
    assert r.status_code == 201, r.json
    for x in (a, b):
        sold = get(c, x)
        assert (sold["status"], sold["status_date"], sold["sale_price"], sold["barn_id"]) == ("sold", "2026-11-10", 840, None)
        assert sold["last_barn_id"] == fold["id"] and sold["sale_tx_id"] == r.json["id"]
    assert get(c, keep)["status"] == "active"
    bilan = c.get("/v1/finance/bilan").json
    assert bilan["sales_total"] == 1680 and bilan["sales_count"] == 2 and bilan["herd_count"] == 1
    [one] = bilan["sales"]
    assert (one["count"], one["amount"], one["average_price"], one["label"]) == (2, 1680, 840, "Sale to the butcher")
    lines = {x["ear_tag"]: x for x in one["animals"]}
    assert (lines["S1"]["sale_price"], lines["S1"]["purchase_price"], lines["S1"]["expenses"],
            lines["S1"]["total_cost"], lines["S1"]["result"]) == (840, 600, 100, 700, 140)
    assert lines["S2"]["result"] == 340 and one["total_cost"] == 1200 and one["result"] == 480
    assert c.get(f"/v1/animals/{a['id']}/costs").json["result"] == 140
    # the barn's balance sheet still counts its sale
    assert c.get(f"/v1/finance/bilan?barn_id={fold['id']}").json["sales"][0]["count"] == 2


def test_cents_add_up_to_the_price(make_client):
    c = farm_client(make_client)
    animals = [add(c, f"S{i}") for i in range(3)]
    sale(c, 100, animals)
    assert sorted(get(c, x)["sale_price"] for x in animals) == [33.33, 33.33, 33.34]


def test_editing_and_deleting_a_sale_moves_the_animals(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a, b = add(c, "S1", barn_id=fold["id"]), add(c, "S2", barn_id=fold["id"])
    tx = sale(c, 1000, [a, b]).json
    # new price and date: on the animals
    c.patch(f"/v1/transactions/{tx['id']}", json={"amount": 1200, "date": "2026-11-12"})
    assert (get(c, a)["sale_price"], get(c, a)["status_date"]) == (600, "2026-11-12")
    # an animal taken out of the sale is back on the farm, in its barn
    r = c.patch(f"/v1/transactions/{tx['id']}", json={"animal_ids": [a["id"]]})
    assert r.status_code == 200, r.json
    back = get(c, b)
    assert (back["status"], back["barn_id"], back["sale_price"], back["sale_tx_id"]) == ("active", fold["id"], None, None)
    assert get(c, a)["sale_price"] == 1200
    # deleted: every animal is back
    assert c.delete(f"/v1/transactions/{tx['id']}").status_code == 204
    assert get(c, a)["status"] == "active" and get(c, a)["barn_id"] == fold["id"]
    assert c.get("/v1/finance/bilan").json["sales"] == []


def test_an_animal_that_left_cannot_be_sold_again(make_client):
    c = farm_client(make_client)
    a, dead = add(c, "S1"), add(c, "S2")
    status(c, dead, "deceased", date="2026-11-01")
    r = sale(c, 500, [a, dead])
    assert r.status_code == 409 and "no longer on the farm" in r.json["detail"]
    assert dead["farm_code"] in r.json["detail"]
    ar = c.post("/v1/transactions", headers={"Accept-Language": "ar"}, json={
        "type": "income", "category": "animal_sale", "amount": 500, "date": "2026-11-10", "animal_ids": [dead["id"]]})
    assert ar.json["detail"] == f"{dead['farm_code']} لم يعد في الضيعة: لا يمكن بيعه. احذفه من هذا البيع"
    assert get(c, a)["status"] == "active"
    tx = sale(c, 500, [a]).json
    assert sale(c, 400, [a]).status_code == 409
    # the same sale can be edited
    assert c.patch(f"/v1/transactions/{tx['id']}", json={"description": "Market"}).status_code == 200
    assert get(c, a)["status"] == "sold"


def test_a_single_sale_from_the_profile_stays_in_step_with_its_entry(make_client):
    c = farm_client(make_client)
    a = add(c, "S1", purchase_price=300)
    status(c, a, "sold", date="2026-11-05", sale_price=500, buyer="Ali")
    tx_id = get(c, a)["sale_tx_id"]
    r = c.patch(f"/v1/transactions/{tx_id}", json={"amount": 550})
    assert r.status_code == 200, r.json
    sold = get(c, a)
    assert (sold["status"], sold["sale_price"]) == ("sold", 550)
    [one] = c.get("/v1/finance/bilan").json["sales"]
    assert (one["count"], one["amount"], one["result"]) == (1, 550, 250)


def test_upgrade_sells_the_animals_of_old_bulk_sales(make_client, repo):
    from scripts.upgrade_2026_11_16 import upgrade

    c = farm_client(make_client)
    a, b = add(c, "S1"), add(c, "S2")
    farm_id = c.get("/v1/farm").json["id"]
    repo.create(f"farms/{farm_id}/transactions", {"type": "income", "category": "animal_sale", "amount": 900,
                                                  "date": "2026-11-03", "animal_ids": [a["id"], b["id"]]})
    assert get(c, a)["status"] == "active"
    assert upgrade(repo) == 2
    assert get(c, a)["status"] == "sold" and get(c, b)["sale_price"] == 450
    assert upgrade(repo) == 0
