"""14 Nov 2026: several farms per account, deleting a farm, mixed barns, deleting a barn with its animals, animals
that leave the farm, expenses shared by barn or animals, animal costs and the herd balance sheet (bilan)."""
import time

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}


def farm_client(make_client, uid="owner1", **extra):
    c = make_client(uid, name=uid.title(), **extra)
    assert c.post("/v1/farms", json=FARM).status_code == 201
    return c


def add(c, tag, species="sheep", **kw):
    r = c.post("/v1/animals", json={"ear_tag": tag, "species": species, "sex": "female", **kw})
    assert r.status_code == 201, r.json
    return r.json


def expense(c, amount, category="feed", **kw):
    r = c.post("/v1/transactions", json={"type": "expense", "category": category, "amount": amount,
                                         "date": "2026-11-01", **kw})
    assert r.status_code == 201, r.json
    return r.json


def status(c, animal, st, **kw):
    return c.post(f"/v1/animals/{animal['id']}/status", json={"status": st, **kw})


# ------------------------------------------------------------------ several farms

def test_several_farms_and_switching(make_client):
    owner = farm_client(make_client)
    first = owner.get("/v1/farm").json["id"]
    r = owner.post("/v1/farms", json={"name": "Second Farm", "address": "Route de Tunis, Bizerte"})
    assert r.status_code == 201 and r.json["farms_count"] == 2
    second = owner.get("/v1/farm").json["id"]
    assert second != first
    farms = owner.get("/v1/me/farms").json
    assert [f["name"] for f in farms] == ["Green Valley Farm", "Second Farm"]
    assert [f["current"] for f in farms] == [False, True] and {f["role"] for f in farms} == {"owner"}
    add(owner, "S-1")  # in the second farm
    assert owner.post("/v1/me/farm", json={"farm_id": first}).json["farm"]["id"] == first
    assert owner.get("/v1/animals").json == []  # data stays separate
    assert owner.post("/v1/me/farm", json={"farm_id": "nope"}).status_code == 403


def test_join_another_farm_while_working_in_one(make_client):
    a = farm_client(make_client, "ownera")
    b = make_client("ownerb", name="B")
    assert b.post("/v1/farms", json={"name": "Bee Farm", "address": "Route de Mateur, Bizerte"}).status_code == 201
    code = b.get("/v1/farm").json["invite_code"]
    a_farm = a.get("/v1/farm").json["id"]
    r = a.post("/v1/farms/join", json={"invite_code": code})
    assert r.status_code == 200 and r.json["status"] == "active" and r.json["farm"]["id"] == a_farm  # stays in A
    assert [f["status"] for f in a.get("/v1/me/farms").json] == ["active", "pending"]
    assert b.post("/v1/farm/members/ownera/approve", json={"role": "worker"}).status_code == 200
    assert a.get("/v1/me").json["farm"]["id"] == a_farm  # not moved while working
    assert a.get("/v1/me").json["farms_count"] == 2
    assert a.post("/v1/farms/join", json={"invite_code": code}).status_code == 409  # already a member


def test_delete_farm_needs_owner_and_recent_password(make_client, repo):
    old = farm_client(make_client, "own", auth_time=int(time.time()) - 3600)
    assert old.delete("/v1/farm").json["code"] == "recent_login_required"
    code = old.get("/v1/farm").json["invite_code"]
    farm_id = old.get("/v1/farm").json["id"]
    worker = make_client("wk", name="W", auth_time=int(time.time()))
    worker.post("/v1/farms/join", json={"invite_code": code})
    old.post("/v1/farm/members/wk/approve", json={"role": "manager"})
    assert worker.delete("/v1/farm").status_code == 403  # a manager cannot
    fresh = make_client("own", auth_time=int(time.time()))
    assert fresh.delete("/v1/farm").status_code == 204
    assert repo.get("farms", farm_id) is None
    assert fresh.get("/v1/me").json["status"] == "none"
    assert worker.get("/v1/me").json["status"] == "none"


def test_delete_account_with_two_farms_deletes_both(make_client, repo):
    c = farm_client(make_client)
    c.post("/v1/farms", json={"name": "Second Farm", "address": "Route de Tunis, Bizerte"})
    assert len(repo.list("farms")) == 2
    assert c.delete("/v1/me").status_code == 204
    assert repo.list("farms") == []


# ------------------------------------------------------------------ barns

def test_mixed_barn_and_old_single_species(make_client):
    c = farm_client(make_client)
    mixed = c.post("/v1/barns", json={"name": "Fold", "species_list": ["sheep", "goat", "sheep"]}).json
    assert mixed["species_list"] == ["sheep", "goat"] and mixed["species"] is None
    add(c, "S1", "sheep", barn_id=mixed["id"])
    add(c, "G1", "goat", barn_id=mixed["id"])
    r = c.post("/v1/animals", json={"ear_tag": "C1", "species": "cattle", "sex": "female", "barn_id": mixed["id"]})
    assert r.status_code == 422
    r = c.post("/v1/animals", json={"ear_tag": "C1", "species": "cattle", "sex": "female", "barn_id": mixed["id"]},
               headers={"Accept-Language": "ar"})
    assert "cattle" not in r.json["detail"] and "أبقار" in r.json["detail"]
    old = c.post("/v1/barns", json={"name": "Shed", "species": "cattle"}).json
    assert old["species_list"] == ["cattle"] and old["species"] == "cattle"
    # narrowing a mixed barn that holds goats to sheep only is refused
    assert c.patch(f"/v1/barns/{mixed['id']}", json={"species_list": ["sheep"]}).status_code == 422
    assert c.patch(f"/v1/barns/{mixed['id']}", json={"species": None}).json["species_list"] == []  # any


def test_delete_barn_moves_animals(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold", "species_list": ["sheep"]}).json
    shed = c.post("/v1/barns", json={"name": "Shed", "species_list": ["cattle"]}).json
    big = c.post("/v1/barns", json={"name": "Big"}).json
    a = add(c, "S1", barn_id=fold["id"])
    assert c.delete(f"/v1/barns/{fold['id']}?move_to={shed['id']}").status_code == 422  # sheep in a cow shed
    assert c.get(f"/v1/animals/{a['id']}").json["barn_id"] == fold["id"]  # nothing changed
    assert c.delete(f"/v1/barns/{fold['id']}?move_to={big['id']}").status_code == 204
    assert c.get(f"/v1/animals/{a['id']}").json["barn_id"] == big["id"]
    assert c.delete(f"/v1/barns/{big['id']}").status_code == 204  # no move_to: outside
    assert c.get(f"/v1/animals/{a['id']}").json["barn_id"] is None


# ------------------------------------------------------------------ leaving the farm

def test_sold_or_dead_animal_leaves_barn_and_cannot_leave_twice(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a = add(c, "S1", barn_id=fold["id"], purchase_price=500)
    r = status(c, a, "sold", sale_price=700)
    assert r.json["barn_id"] is None and r.json["last_barn_id"] == fold["id"] and r.json["last_barn_name"] == "Fold"
    assert status(c, a, "sold", sale_price=750).status_code == 200  # correcting the price
    assert status(c, a, "deceased").status_code == 409  # cannot die after being sold
    assert status(c, a, "gifted").status_code == 409
    incomes = [t for t in c.get("/v1/transactions").json if t["type"] == "income"]
    assert [t["amount"] for t in incomes] == [750]
    assert c.post("/v1/animals/move", json={"animal_ids": [a["id"]], "barn_id": fold["id"]}).status_code == 422
    assert c.patch(f"/v1/animals/{a['id']}", json={"barn_id": fold["id"]}).status_code == 422
    outside = c.get("/v1/animals", query_string={"barn_id": "none", "status": "sold"}).json
    assert [x["id"] for x in outside] == [a["id"]]
    undo = status(c, a, "active")
    assert undo.json["barn_id"] == fold["id"] and undo.json["last_barn_id"] is None
    assert [t for t in c.get("/v1/transactions").json if t["type"] == "income"] == []


# ------------------------------------------------------------------ expenses, costs, bilan

def test_whole_barn_and_chosen_animals_expenses_and_animal_costs(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a1 = add(c, "S1", barn_id=fold["id"], purchase_price=600)
    a2 = add(c, "S2", barn_id=fold["id"], purchase_price=400)
    add(c, "S3", purchase_price=300)  # outside
    feed = expense(c, 300, barn_id=fold["id"], whole_barn=True)
    assert sorted(feed["animal_ids"]) == sorted([a1["id"], a2["id"]]) and feed["share"] == 150 and feed["barn_name"] == "Fold"
    vet = expense(c, 80, "veterinary", barn_id=fold["id"], animal_ids=[a1["id"]])
    assert vet["animal_id"] == a1["id"] and vet["share"] is None
    assert c.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 5, "date": "2026-11-01",
                                            "whole_barn": True}).status_code == 422
    costs = c.get(f"/v1/animals/{a1['id']}/costs").json
    assert costs["purchase_price"] == 600 and costs["expenses_total"] == 230 and costs["health_total"] == 80
    assert costs["total_cost"] == 830 and costs["result"] is None
    assert {(l["category"], l["amount"], l["shared_with"]) for l in costs["expenses"]} == {("feed", 150, 2), ("veterinary", 80, 1)}
    status(c, a1, "sold", sale_price=1000)
    assert c.get(f"/v1/animals/{a1['id']}/costs").json["result"] == 170
    # emptying the animals of a one-animal expense clears it (animal_id included)
    cleared = c.patch(f"/v1/transactions/{vet['id']}", json={"animal_ids": []}).json
    assert cleared["animal_ids"] == [] and cleared["animal_id"] is None
    c.patch(f"/v1/transactions/{vet['id']}", json={"animal_ids": [a1["id"]]})
    # a later whole-barn edit of the amount keeps the same animals
    edited = c.patch(f"/v1/transactions/{feed['id']}", json={"amount": 400}).json
    assert sorted(edited["animal_ids"]) == sorted([a1["id"], a2["id"]])


def test_bilan_example_and_dead_animal(make_client):
    """The farmer's example: buy, spend, sell, then the real profit; a dead animal's price becomes an expense."""
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    sheep = [add(c, f"S{i}", barn_id=fold["id"], purchase_price=500) for i in range(4)]  # 2 000 of capital
    expense(c, 400, barn_id=fold["id"], whole_barn=True)  # 100 each
    expense(c, 50, "utilities")  # farm-wide, no animal
    status(c, sheep[0], "sold", sale_price=900)
    status(c, sheep[1], "deceased")
    b = c.get("/v1/finance/bilan").json
    assert (b["purchases_total"], b["purchases_count"]) == (2000, 4)
    assert (b["lost_purchases"], b["lost_count"], b["capital"]) == (500, 1, 1500)
    assert b["expenses_by_category"] == {"feed": 400, "utilities": 50}
    assert (b["operating_expenses"], b["expenses_total"]) == (450, 950)
    assert (b["sales_total"], b["sales_count"], b["cash_in"]) == (900, 1, 900)
    assert (b["herd_count"], b["herd_value"]) == (2, 1200)  # 2 x (500 + 100)
    assert b["profit"] == round(900 + 1200 - 1500 - 950, 2)
    # the purchase_animal transactions are capital, never counted as expenses
    assert "purchase_animal" not in b["expenses_by_category"]
    fb = c.get(f"/v1/finance/bilan?barn_id={fold['id']}").json
    assert fb["expenses_by_category"] == {"feed": 400} and fb["herd_count"] == 2 and fb["sales_count"] == 1
    assert c.get("/v1/finance/bilan?barn_id=nope").status_code == 404


def test_costs_and_bilan_are_for_managers(make_client):
    owner = farm_client(make_client)
    a = add(owner, "S1")
    code = owner.get("/v1/farm").json["invite_code"]
    w = make_client("wk", name="W")
    w.post("/v1/farms/join", json={"invite_code": code})
    owner.post("/v1/farm/members/wk/approve", json={"role": "worker"})
    assert w.get(f"/v1/animals/{a['id']}/costs").status_code == 403
    assert w.get("/v1/finance/bilan").status_code == 403


def test_auto_descriptions_in_the_readers_language(make_client):
    c = farm_client(make_client)
    a = add(c, "S1", purchase_price=500)
    status(c, a, "sold", sale_price=900, buyer="Salah")
    rows = c.get("/v1/transactions", headers={"Accept-Language": "ar"}).json
    labels = {t["category"]: t["label"] for t in rows}
    assert labels["purchase_animal"] == "شراء S1" and labels["animal_sale"] == "بيع S1 إلى Salah"


def test_upgrade_script_takes_left_animals_out_of_barns(make_client, repo):
    from scripts.upgrade_2026_11_14 import upgrade

    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a = add(c, "S1", barn_id=fold["id"])
    farm_id = c.get("/v1/farm").json["id"]
    repo.update(f"farms/{farm_id}/animals", a["id"], {"status": "sold"})  # as stored before this release
    assert upgrade(repo) == 1 and upgrade(repo) == 0
    got = c.get(f"/v1/animals/{a['id']}").json
    assert got["barn_id"] is None and got["last_barn_id"] == fold["id"]


def test_purchase_entered_by_hand_is_capital(make_client):
    """20 sheep bought in one go and booked as one "purchase animal" expense: capital, shared between them."""
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a, b = add(c, "S1", barn_id=fold["id"]), add(c, "S2", barn_id=fold["id"])
    expense(c, 1000, "purchase_animal", barn_id=fold["id"], animal_ids=[a["id"], b["id"]])
    expense(c, 300, "purchase_animal")  # no animal named: farm-wide capital
    bilan = c.get("/v1/finance/bilan").json
    assert (bilan["purchases_total"], bilan["purchases_count"], bilan["capital"]) == (1300, 2, 1300)
    assert "purchase_animal" not in bilan["expenses_by_category"] and bilan["expenses_total"] == 0
    assert bilan["herd_value"] == 1000 and bilan["profit"] == -300
    fb = c.get(f"/v1/finance/bilan?barn_id={fold['id']}").json
    assert fb["purchases_total"] == 1000 and fb["profit"] == 0
    costs = c.get(f"/v1/animals/{a['id']}/costs").json
    assert (costs["purchase_price"], costs["expenses_total"], costs["total_cost"]) == (500, 0, 500)
    assert costs["expenses"] == []
    # one of them dies: its share moves to expenses
    status(c, b, "deceased")
    bilan = c.get("/v1/finance/bilan").json
    assert (bilan["lost_purchases"], bilan["capital"], bilan["expenses_total"]) == (500, 800, 500)
    assert bilan["profit"] == round(500 - 800 - 500, 2)


def test_deleted_animal_keeps_its_money_in_the_farm_bilan(make_client):
    c = farm_client(make_client)
    a = add(c, "S1", purchase_price=1000)
    expense(c, 200, animal_ids=[a["id"]])
    status(c, a, "sold", sale_price=1500)
    before = c.get("/v1/finance/bilan").json["profit"]
    assert before == 300
    assert c.delete(f"/v1/animals/{a['id']}").status_code == 204
    after = c.get("/v1/finance/bilan").json
    assert after["profit"] == 300 and after["sales_total"] == 1500 and after["purchases_total"] == 1000

