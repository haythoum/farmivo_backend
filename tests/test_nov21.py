"""21 November 2026 (client feedback): health costs booked in Finance, a sale at 0 is an entry, the cash box."""
from __future__ import annotations

from tests.test_nov14 import add, farm_client


def _worker(make_client, owner):
    code = owner.get("/v1/farm").json["invite_code"]
    w = make_client("w1")
    w.post("/v1/farms/join", json={"invite_code": code})
    owner.post("/v1/farm/members/w1/approve", json={"role": "worker"})
    return w


def _txs(c):
    return c.get("/v1/transactions").json


def test_a_vaccination_with_a_cost_books_the_expense(make_client):
    c = farm_client(make_client)
    a = add(c, "S1")
    v = c.post("/v1/vaccinations", json={"animal_id": a["id"], "vaccine_name": "PPR", "date_given": "2026-11-20",
                                         "cost": 12.5}).json
    tx = c.get(f"/v1/transactions/{v['transaction_id']}").json
    assert (tx["type"], tx["category"], tx["amount"], tx["animal_ids"]) == ("expense", "veterinary", 12.5, [a["id"]])
    assert tx["label"].startswith("Vaccination: PPR")
    ar = c.get(f"/v1/transactions/{v['transaction_id']}", headers={"Accept-Language": "ar"}).json
    assert ar["label"].startswith("تلقيح: PPR")
    assert c.get(f"/v1/animals/{a['id']}/costs").json["expenses_total"] == 12.5
    c.patch(f"/v1/vaccinations/{v['id']}", json={"cost": 20})
    assert c.get(f"/v1/transactions/{v['transaction_id']}").json["amount"] == 20
    c.patch(f"/v1/vaccinations/{v['id']}", json={"cost": None})
    assert c.get(f"/v1/transactions/{v['transaction_id']}").status_code == 404


def test_treatment_and_vet_visit_costs(make_client):
    c = farm_client(make_client)
    a = add(c, "S1")
    t = c.post("/v1/treatments", json={"animal_id": a["id"], "name": "Wormer", "start_date": "2026-11-20", "cost": 8}).json
    v = c.post("/v1/vet-visits", json={"animal_id": a["id"], "reason": "Lame", "visit_date": "2026-11-20", "cost": 40}).json
    assert c.get(f"/v1/transactions/{t['transaction_id']}").json["category"] == "medication"
    assert c.get(f"/v1/transactions/{v['transaction_id']}").json["category"] == "veterinary"
    c.delete(f"/v1/vet-visits/{v['id']}")
    assert c.get(f"/v1/transactions/{v['transaction_id']}").status_code == 404
    # deleting the expense in Finance unlinks the treatment
    c.delete(f"/v1/transactions/{t['transaction_id']}")
    again = c.get(f"/v1/treatments/{t['id']}").json
    assert again["transaction_id"] is None and again["cost"] is None


def test_a_whole_barn_vaccination_cost_is_one_shared_expense(make_client):
    c = farm_client(make_client)
    barn = c.post("/v1/barns", json={"name": "Fold", "species": "sheep"}).json
    ids = [add(c, f"S{n}", barn_id=barn["id"])["id"] for n in range(4)]
    r = c.post("/v1/vaccinations/bulk", json={"barn_id": barn["id"], "vaccine_name": "PPR", "date_given": "2026-11-20",
                                              "cost": 60}).json
    tx = c.get(f"/v1/transactions/{r['transaction_id']}").json
    assert tx["amount"] == 60 and sorted(tx["animal_ids"]) == sorted(ids) and tx["share"] == 15
    assert c.get(f"/v1/animals/{ids[0]}/costs").json["expenses_total"] == 15


def test_workers_record_health_without_money(make_client):
    owner = farm_client(make_client)
    a = add(owner, "S1")
    w = _worker(make_client, owner)
    body = {"animal_id": a["id"], "vaccine_name": "PPR", "date_given": "2026-11-20"}
    assert w.post("/v1/vaccinations", json={**body, "cost": 5}).status_code == 403
    v = w.post("/v1/vaccinations", json=body).json
    owner.patch(f"/v1/vaccinations/{v['id']}", json={"cost": 9})
    seen = w.get(f"/v1/vaccinations/{v['id']}").json
    assert seen["cost"] is None and seen["transaction_id"] is None
    w.patch(f"/v1/vaccinations/{v['id']}", json={"notes": "ok"})
    assert owner.get(f"/v1/vaccinations/{v['id']}").json["cost"] == 9  # kept


def test_a_sale_at_zero_is_an_entry(make_client):
    c = farm_client(make_client)
    a = add(c, "S1")
    r = c.post(f"/v1/animals/{a['id']}/status", json={"status": "sold", "sale_price": 0, "date": "2026-11-20"})
    assert r.status_code == 200 and r.json["sale_tx_id"]
    tx = [t for t in _txs(c) if t["category"] == "animal_sale"]
    assert len(tx) == 1 and tx[0]["amount"] == 0 and tx[0]["label"] == "Sale of S1"
    bilan = c.get("/v1/finance/bilan").json
    assert bilan["sales_count"] == 1 and bilan["sales"][0]["label"] == "Sale of S1"
    # a price can be given later in Finance; a typed expense at 0 is still refused
    assert c.patch(f"/v1/transactions/{tx[0]['id']}", json={"amount": 800}).status_code == 200
    assert c.get(f"/v1/animals/{a['id']}").json["sale_price"] == 800
    assert c.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 0,
                                            "date": "2026-11-20"}).status_code == 422


def test_the_cash_box(make_client):
    c = farm_client(make_client)
    add(c, "S1")
    c.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 99, "date": "2026-10-01"})
    assert c.get("/v1/cash").json["balance"] == 0  # nothing put in yet
    c.post("/v1/cash/moves", json={"amount": 15000, "date": "2026-11-01", "who": "Jamil", "note": "Capital"})
    c.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 400, "date": "2026-11-05"})
    c.post("/v1/transactions", json={"type": "income", "category": "milk_sale", "amount": 150, "date": "2026-11-06"})
    w = _worker(make_client, c)
    assert w.post("/v1/cash/moves", json={"amount": 1000, "date": "2026-11-07"}).status_code == 201
    assert w.post("/v1/cash/moves", json={"amount": 10, "direction": "out"}).status_code == 403
    assert w.get("/v1/cash").status_code == 403
    box = c.get("/v1/cash").json
    assert (box["since"], box["put_in"], box["expenses"], box["income"]) == ("2026-11-01", 16000, 400, 150)
    assert box["balance"] == 15750 and box["moves"][0]["by"]
    c.post("/v1/cash/moves", json={"amount": 750, "direction": "out", "note": "Family"})
    assert c.get("/v1/cash").json["balance"] == 15000


def test_upgrade_gives_old_sales_without_entry_their_entry(make_client, repo):
    from scripts.upgrade_2026_11_21 import upgrade

    c = farm_client(make_client)
    a = add(c, "S1")
    farm_id = c.get("/v1/farm").json["id"]
    repo.update(f"farms/{farm_id}/animals", a["id"], {"status": "sold", "status_date": "2026-11-10", "sale_price": None})
    assert upgrade(repo) == 1 and upgrade(repo) == 0
    tx = [t for t in c.get("/v1/transactions").json if t["category"] == "animal_sale"]
    assert tx[0]["amount"] == 0 and tx[0]["date"] == "2026-11-10"
    assert c.get(f"/v1/animals/{a['id']}").json["sale_tx_id"] == tx[0]["id"]
