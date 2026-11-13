"""Review of 13 Nov 2026: password reset email, age by teeth, ear tags per species, purchase price, animal
statuses (sold, charity, gift, sacrifice), barns, the breeding flow (pending is not pregnant) and finance."""
from datetime import timedelta

import pytest

from app.services import password_reset
from app.utils import today


def join(make_client, owner, uid, role="worker"):
    """A client for ``uid`` that joined the owner's farm and was approved with ``role``."""
    c = make_client(uid, name=uid.title())
    code = owner.get("/v1/farm").json["invite_code"]
    assert c.post("/v1/farms/join", json={"invite_code": code}).status_code == 200
    assert owner.post(f"/v1/farm/members/{uid}/approve", json={"role": role}).status_code == 200
    return c


def iso(days=0):
    return (today() + timedelta(days=days)).isoformat()


def add(client, **fields):
    data = {"ear_tag": "001", "species": "goat", "sex": "female", **fields}
    return client.post("/v1/animals", json=data)


# ------------------------------------------------------------------ forgot password
@pytest.fixture
def anon(make_client):
    """A client with a fake Firebase link maker: known@x.tn has an account, nobody else."""
    def make_link(email):
        if email != "known@x.tn":
            raise password_reset.NoSuchUser(email)
        return "https://farmivo-4d932.firebaseapp.com/__/auth/action?mode=resetPassword&oobCode=abc&lang=en"
    return make_client("anon", reset_link=make_link)


def test_password_reset_sends_branded_email_in_the_app_language(anon, mailer):
    r = anon.post("/v1/auth/password-reset", json={"email": " Known@X.tn "}, headers={"Accept-Language": "fr"})
    assert r.status_code == 204
    to, link, lang = mailer.resets[-1]
    assert to == "known@x.tn" and lang == "fr"
    assert "oobCode=abc" in link and link.endswith("lang=fr") and link.count("lang=") == 1


def test_password_reset_unknown_address_is_silent(anon, mailer):
    assert anon.post("/v1/auth/password-reset", json={"email": "nobody@x.tn"}).status_code == 204
    assert mailer.resets == []


def test_password_reset_limits_and_errors(anon, mailer, monkeypatch):
    assert anon.post("/v1/auth/password-reset", json={"email": "not-an-email"}).status_code == 422
    assert anon.post("/v1/auth/password-reset", json={"email": "known@x.tn"}).status_code == 204
    r = anon.post("/v1/auth/password-reset", json={"email": "known@x.tn"})
    assert r.status_code == 429 and r.json["code"] == "too_soon" and r.json["retry_after"] > 0
    mailer.fail = True
    later = password_reset.now() + timedelta(minutes=2)
    monkeypatch.setattr(password_reset, "now", lambda: later)
    r = anon.post("/v1/auth/password-reset", json={"email": "known@x.tn"})
    assert r.status_code == 502 and r.json["code"] == "email_failed"


def test_password_reset_html_has_the_link_and_is_rtl_in_arabic():
    from app.services.mailer import reset_html, reset_message

    html = reset_html("https://x.example/a?b=1&c=2", "ar")
    assert 'dir="rtl"' in html and "https://x.example/a?b=1&amp;c=2" in html
    msg = reset_message("contact@quadralens.tn", "Farmivo", "a@b.tn", "https://x", "en")["Messages"][0]
    assert msg["Subject"] == "Reset your Farmivo password" and msg["CustomID"] == "farmivo-password-reset"


# ------------------------------------------------------------------ ear tags, age, price
def test_same_ear_tag_allowed_for_another_species(client):
    assert add(client).status_code == 201
    assert add(client, species="dog", sex="male").status_code == 201
    r = add(client)
    assert r.status_code == 409 and "goat" in r.json["detail"]
    fr = client.post("/v1/animals", json={"ear_tag": "001", "species": "goat", "sex": "male"},
                     headers={"Accept-Language": "fr"})
    assert fr.status_code == 409 and "boucle" in fr.json["detail"]
    dog = client.get("/v1/animals", query_string={"species": "dog"}).json[0]
    # changing the dog into a goat collides with the goat 001
    assert client.patch(f"/v1/animals/{dog['id']}", json={"species": "goat"}).status_code == 409
    assert client.patch(f"/v1/animals/{dog['id']}", json={"species": "cat"}).status_code == 200


def test_age_class_by_species(client):
    r = add(client, age_class="four_teeth")
    assert r.status_code == 201 and r.json["age_class"] == "four_teeth"
    assert r.json["age_class_label"].startswith("4 teeth")
    ar = client.get(f"/v1/animals/{r.json['id']}", headers={"Accept-Language": "ar"}).json
    assert ar["age_class_label"].startswith("4 أسنان")
    bad = add(client, ear_tag="002", age_class="cups")  # a horse class on a goat
    assert bad.status_code == 422
    assert add(client, ear_tag="003", species="pig", age_class="milk_teeth").status_code == 422
    # changing the species drops the old class instead of failing
    changed = client.patch(f"/v1/animals/{r.json['id']}", json={"species": "pig"}).json
    assert changed["species"] == "pig" and changed["age_class"] is None
    catalog = client.get("/v1/age-classes", headers={"Accept-Language": "fr"}).json
    assert [c["key"] for c in catalog["cattle"]][:2] == ["milk_teeth", "two_teeth"]
    assert catalog["horse"][0]["label"].startswith("Dents de lait") and "pig" not in catalog
    assert set(catalog) == {"cattle", "sheep", "goat", "horse", "dog", "cat"}


def finance(client):
    return client.get("/v1/finance/summary").json


def test_purchase_price_books_one_expense_and_follows_edits(client):
    a = add(client, purchase_price=350, origin="purchased").json
    assert a["purchase_price"] == 350
    assert finance(client)["expenses_by_category"] == {"purchase_animal": 350.0}
    client.patch(f"/v1/animals/{a['id']}", json={"purchase_price": 400})
    assert finance(client)["expenses"] == 400.0
    client.patch(f"/v1/animals/{a['id']}", json={"origin": "born_on_farm"})
    assert finance(client)["expenses"] == 0.0
    client.patch(f"/v1/animals/{a['id']}", json={"origin": "purchased"})
    assert finance(client)["expenses"] == 400.0
    client.patch(f"/v1/animals/{a['id']}", json={"purchase_price": None})
    assert finance(client)["expenses"] == 0.0
    born = add(client, ear_tag="002", origin="born_on_farm", purchase_price=100).json
    assert born["purchase_price"] == 100 and finance(client)["expenses"] == 0.0


# ------------------------------------------------------------------ statuses
def test_sale_income_is_never_counted_twice(client):
    a = add(client).json
    sell = lambda price: client.post(f"/v1/animals/{a['id']}/status", json={"status": "sold", "sale_price": price,
                                                                             "buyer": "Salah"})
    assert sell(500).json["sale_price"] == 500
    assert finance(client)["income"] == 500.0
    assert sell(650).status_code == 200  # price corrected
    assert finance(client)["income"] == 650.0
    back = client.post(f"/v1/animals/{a['id']}/status", json={"status": "active"}).json
    assert back["status"] == "active" and back["buyer"] is None and finance(client)["income"] == 0.0
    sell(700)
    assert finance(client)["income"] == 700.0 and len(client.get("/v1/transactions").json) == 1
    dash = client.get("/v1/dashboard").json
    assert dash["finance"]["income"] == 700.0 and dash["movements"]["sales"] == 1


@pytest.mark.parametrize("status", ["donated", "gifted", "sacrificed"])
def test_leaving_statuses_close_reminders_and_count(client, status):
    a = add(client, date_of_birth=iso(-400)).json
    client.post("/v1/vaccinations", json={"animal_id": a["id"], "vaccine_name": "PPR", "date_given": iso(),
                                          "next_due_date": iso(30)})
    r = client.post(f"/v1/animals/{a['id']}/status", json={"status": status, "recipient": "Mosque", "notes": "Eid"})
    assert r.status_code == 200 and r.json["status"] == status
    assert r.json["recipient"] == ("Mosque" if status != "sacrificed" else None)
    assert client.get("/v1/reminders", query_string={"status": "pending"}).json == []
    assert client.get("/v1/animals", query_string={"status": "on_farm"}).json == []
    dash = client.get("/v1/dashboard").json
    assert dash["animals"]["total"] == 0
    key = "sacrificed" if status == "sacrificed" else "given"
    assert dash["movements"][key] == 1
    assert finance(client)["income"] == 0.0


def test_status_date_cannot_be_in_the_future(client):
    a = add(client).json
    assert client.post(f"/v1/animals/{a['id']}/status", json={"status": "sold", "date": iso(3)}).status_code == 422


# ------------------------------------------------------------------ barns
def test_barns_crud_filters_and_species_rule(client, make_client):
    fold = client.post("/v1/barns", json={"name": "Sheepfold", "species": "sheep", "capacity": 80}).json
    stable = client.post("/v1/barns", json={"name": "Stable"}).json
    assert client.post("/v1/barns", json={"name": " sheepfold "}).status_code == 409
    ewe = add(client, species="sheep", barn_id=fold["id"]).json
    assert ewe["barn_id"] == fold["id"] and ewe["barn_name"] == "Sheepfold"
    r = add(client, ear_tag="h1", species="horse", sex="male", barn_id=fold["id"])
    assert r.status_code == 422 and "Sheepfold" in r.json["detail"]
    horse = add(client, ear_tag="h1", species="horse", sex="male", barn_id=stable["id"]).json
    assert add(client, ear_tag="x", barn_id="nope").status_code == 404
    barns = {b["name"]: b for b in client.get("/v1/barns").json}
    assert barns["Sheepfold"]["animal_count"] == 1 and barns["Stable"]["animal_count"] == 1
    assert [a["ear_tag"] for a in client.get("/v1/animals", query_string={"barn_id": fold["id"]}).json] == ["001"]
    assert client.get("/v1/animals", query_string={"barn_id": "none"}).json == []
    # the stable cannot become a sheep-only barn while a horse is inside
    assert client.patch(f"/v1/barns/{stable['id']}", json={"species": "sheep"}).status_code == 422
    assert client.patch(f"/v1/barns/{stable['id']}", json={"name": "Horse stable"}).json["name"] == "Horse stable"
    # a worker can read barns and put animals in them, but not manage barns
    worker = join(make_client, client, "w1")
    assert len(worker.get("/v1/barns").json) == 2
    assert worker.post("/v1/barns", json={"name": "Shed"}).status_code == 403
    assert worker.patch(f"/v1/animals/{horse['id']}", json={"barn_id": None}).status_code == 200
    # deleting a barn keeps its animals, without a barn
    assert client.delete(f"/v1/barns/{fold['id']}").status_code == 204
    assert client.get(f"/v1/animals/{ewe['id']}").json["barn_id"] is None
    assert client.get("/v1/dashboard").json["animals"]["by_barn"] == {"unknown": 2}


# ------------------------------------------------------------------ breeding
def reminders(client):
    return {r["source_type"]: r for r in client.get("/v1/reminders", query_string={"status": "pending"}).json}


def test_barn_cards_count_what_needs_attention(client):
    shed = client.post("/v1/barns", json={"name": "Cow shed", "species": "cattle", "capacity": 40}).json
    assert (shed["sick_count"], shed["pregnant_count"], shed["vaccines_due_count"]) == (0, 0, 0)
    cow = add(client, species="cattle", barn_id=shed["id"]).json
    sick = add(client, ear_tag="002", species="cattle", barn_id=shed["id"]).json
    later = add(client, ear_tag="003", species="cattle", barn_id=shed["id"]).json
    add(client, ear_tag="004", species="cattle")  # in no barn: never counted
    client.post(f"/v1/animals/{sick['id']}/status", json={"status": "sick"})
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "mating_date": iso(-40)}).json
    client.post("/v1/vaccinations", json={"animal_id": sick["id"], "vaccine_name": "FMD", "date_given": iso(-300),
                                          "next_due_date": iso(-1)})  # overdue
    client.post("/v1/vaccinations", json={"animal_id": later["id"], "vaccine_name": "FMD", "date_given": iso(),
                                          "next_due_date": iso(60)})  # not due soon
    card = client.get("/v1/barns").json[0]
    assert (card["animal_count"], card["sick_count"], card["pregnant_count"], card["vaccines_due_count"]) == (3, 1, 0, 1)
    client.patch(f"/v1/breedings/{b['id']}", json={"pregnancy_status": "confirmed"})  # pending was not pregnant
    assert client.get(f"/v1/barns/{shed['id']}").json["pregnant_count"] == 1


def test_move_animals_to_a_barn_and_outside(client, make_client):
    shed = client.post("/v1/barns", json={"name": "Cow shed", "species": "cattle"}).json
    cows = [add(client, ear_tag=f"00{i}", species="cattle").json for i in range(1, 4)]
    goat = add(client, ear_tag="009", species="goat").json
    ids = [c["id"] for c in cows]
    r = client.post("/v1/animals/move", json={"animal_ids": ids + [ids[0]], "barn_id": shed["id"]})
    assert r.status_code == 200 and r.json == {"moved": 3, "barn_id": shed["id"]}
    assert client.get("/v1/barns").json[0]["animal_count"] == 3
    # all or nothing: a goat cannot go into the cow shed, nothing moves
    r = client.post("/v1/animals/move", json={"animal_ids": [goat["id"]], "barn_id": shed["id"]})
    assert r.status_code == 422
    assert client.get("/v1/animals", query_string={"barn_id": "none"}).json[0]["id"] == goat["id"]
    assert client.post("/v1/animals/move", json={"animal_ids": ["nope"], "barn_id": None}).status_code == 404
    assert client.post("/v1/animals/move", json={"animal_ids": [], "barn_id": None}).status_code == 422
    # back outside (no barn); a sold animal cannot be moved
    assert client.post("/v1/animals/move", json={"animal_ids": ids[:1], "barn_id": None}).json["moved"] == 1
    assert client.post(f"/v1/animals/{ids[1]}/status", json={"status": "sold", "sale_price": 100}).status_code == 200
    r = client.post("/v1/animals/move", json={"animal_ids": [ids[1]], "barn_id": None}, headers={"Accept-Language": "fr"})
    assert r.status_code == 422 and "déplacés" in r.json["detail"]
    # workers can move animals; viewers cannot
    worker = join(make_client, client, "wk")
    assert worker.post("/v1/animals/move", json={"animal_ids": [ids[0]], "barn_id": shed["id"]}).status_code == 200
    viewer = join(make_client, client, "vw", role="viewer")
    assert viewer.post("/v1/animals/move", json={"animal_ids": [ids[0]], "barn_id": None}).status_code == 403


def test_blank_barn_id_means_outside(client):
    shed = client.post("/v1/barns", json={"name": "Shed"}).json
    a = add(client, barn_id="  ").json
    assert a["barn_id"] is None
    assert client.patch(f"/v1/animals/{a['id']}", json={"barn_id": shed["id"]}).json["barn_id"] == shed["id"]
    assert client.patch(f"/v1/animals/{a['id']}", json={"barn_id": ""}).json["barn_id"] is None
    assert client.post("/v1/animals/move", json={"animal_ids": [a["id"]], "barn_id": ""}).json["barn_id"] is None
    assert [x["id"] for x in client.get("/v1/animals", query_string={"barn_id": "none"}).json] == [a["id"]]


def test_pending_mating_is_not_pregnant(client):
    ewe = add(client, species="sheep").json
    b = client.post("/v1/breedings", json={"dam_id": ewe["id"], "mating_date": iso(-5)}).json
    assert b["pregnancy_status"] == "pending" and b["expected_birth_date"] == iso(-5 + 147)
    dash = client.get("/v1/dashboard").json["breeding"]
    assert dash["pregnant_count"] == 0 and dash["awaiting_check_count"] == 1 and dash["due_soon"] == []
    rem = reminders(client)
    assert set(rem) == {"pregnancy_check"} and rem["pregnancy_check"]["due_date"] == iso(-5 + 35)
    # confirming: the check reminder goes, the expected birth reminder comes, the confirmation date is set
    c = client.patch(f"/v1/breedings/{b['id']}", json={"pregnancy_status": "confirmed"}).json
    assert c["pregnancy_confirmed_date"] == iso()
    assert set(reminders(client)) == {"birth"}
    dash = client.get("/v1/dashboard").json["breeding"]
    assert dash["pregnant_count"] == 1 and dash["awaiting_check_count"] == 0
    # not pregnant: no reminder at all
    client.patch(f"/v1/breedings/{b['id']}", json={"pregnancy_status": "not_pregnant"})
    assert reminders(client) == {}
    assert client.get("/v1/dashboard").json["breeding"]["pregnant_count"] == 0


def test_moving_the_mating_date_moves_the_suggested_birth(client):
    cow = add(client, species="cattle").json
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "mating_date": iso(-20)}).json
    moved = client.patch(f"/v1/breedings/{b['id']}", json={"mating_date": iso(-10)}).json
    assert moved["expected_birth_date"] == iso(-10 + 283)
    # a date typed by the farmer is kept
    client.patch(f"/v1/breedings/{b['id']}", json={"expected_birth_date": iso(200)})
    kept = client.patch(f"/v1/breedings/{b['id']}", json={"mating_date": iso(-12)}).json
    assert kept["expected_birth_date"] == iso(200)
    assert client.post("/v1/breedings", json={"dam_id": cow["id"], "mating_date": iso(),
                                              "pregnancy_status": "delivered"}).status_code == 422


def test_birth_tags_per_species_and_barn_follow_the_mother(client):
    fold = client.post("/v1/barns", json={"name": "Fold"}).json
    ewe = add(client, species="sheep", barn_id=fold["id"]).json
    add(client, ear_tag="L1", species="dog", sex="male")  # same number on a dog is fine
    b = client.post("/v1/breedings", json={"dam_id": ewe["id"], "mating_date": iso(-150),
                                           "pregnancy_status": "confirmed"}).json
    r = client.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": iso(), "offspring": [
        {"ear_tag": "L1", "sex": "female"}, {"ear_tag": "L2", "sex": "male"}]})
    assert r.status_code == 201, r.json
    assert {a["barn_id"] for a in r.json["offspring"]} == {fold["id"]}
    assert reminders(client) == {}
    again = client.post("/v1/animals", json={"ear_tag": "L2", "species": "sheep", "sex": "male"})
    assert again.status_code == 409


def test_sync_script_replaces_old_birth_reminders_of_pending_matings(client, repo):
    from app.repository import farm_path
    from scripts.sync_breeding_reminders import sync_all

    ewe = add(client, species="sheep").json
    b = client.post("/v1/breedings", json={"dam_id": ewe["id"], "mating_date": iso(-5)}).json
    farm_id = client.get("/v1/me").json["farm"]["id"]
    # what the old code stored: a birth reminder for a pending mating
    repo.set(farm_path(farm_id, "reminders"), f"birth_{b['id']}", {"source_type": "birth", "status": "pending",
                                                                   "due_date": iso(142), "title": "Expected birth"})
    assert set(reminders(client)) == {"birth", "pregnancy_check"}
    assert sync_all(repo) == 1
    assert set(reminders(client)) == {"pregnancy_check"}


def test_breed_list_and_label(client):
    fr = client.get("/v1/breeds", headers={"Accept-Language": "fr"}).json
    assert fr["sheep"][0] == {"name": "Barbarine", "label": "Barbarine"}
    assert {"name": "Holstein", "label": "Prim'Holstein"} in fr["cattle"] and "other" not in fr
    cow = add(client, species="cattle", breed="Holstein").json
    assert cow["breed"] == "Holstein" and cow["breed_label"] == "Holstein"
    ar = client.get(f"/v1/animals/{cow['id']}", headers={"Accept-Language": "ar"}).json
    assert ar["breed_label"] == "هولشتاين"
    typed = add(client, ear_tag="002", species="cattle", breed="Sahiwal").json  # a breed not in the list
    assert typed["breed_label"] == "Sahiwal"
