"""15 November 2026: colour, what is possible in breeding, miscarriages, expenses always carried by animals (feed by
age), the barn filter of the entries, readable translated messages."""
from __future__ import annotations

import ast
import pathlib
from datetime import timedelta

from app.utils import today
from tests.test_nov14 import add, expense, farm_client, status

AR = {"Accept-Language": "ar"}


def d(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def years_ago(n: float) -> str:
    return (today() - timedelta(days=int(365.25 * n))).isoformat()


def mate(c, dam, sire=None, when=-150, **kw):
    body = {"dam_id": dam["id"], "mating_date": d(when), **kw}
    if sire:
        body["sire_id"] = sire["id"]
    return c.post("/v1/breedings", json=body)


# ------------------------------------------------------------------ colour

def test_colour_is_one_of_the_farm_names(make_client):
    c = farm_client(make_client)
    a = c.post("/v1/animals", json={"species": "sheep", "sex": "female", "color": "sardi"}).json
    assert a["color"] == "sardi"
    assert c.post("/v1/animals", json={"species": "sheep", "sex": "female", "color": "purple"}).status_code == 422


# ------------------------------------------------------------------ breeding rules

def test_one_open_pregnancy_at_a_time(make_client):
    c = farm_client(make_client)
    ewe = add(c, "E1", sex="female", date_of_birth=years_ago(2))
    first = mate(c, ewe, when=-30)
    assert first.status_code == 201
    second = mate(c, ewe, when=-10, headers=None) if False else c.post(
        "/v1/breedings", json={"dam_id": ewe["id"], "mating_date": d(-10)}, headers=AR)
    assert second.status_code == 409 and "لم يُغلق" in second.json["detail"]
    # "not pregnant" closes it: a new mating is fine
    c.patch(f"/v1/breedings/{first.json['id']}", json={"pregnancy_status": "not_pregnant"})
    assert mate(c, ewe, when=-5).status_code == 201


def test_no_mating_while_she_was_pregnant(make_client):
    c = farm_client(make_client)
    ewe = add(c, "E1", sex="female", date_of_birth=years_ago(3))
    b = mate(c, ewe, when=-200).json
    born = c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(-52), "offspring": [{"sex": "male"}]})
    assert born.status_code == 201, born.json
    assert mate(c, ewe, when=-100).status_code == 409  # inside -200 .. -52
    assert mate(c, ewe, when=-30).status_code == 201


def test_minimum_ages(make_client):
    c = farm_client(make_client)
    young_ewe = add(c, "E1", sex="female", date_of_birth=d(-200))  # about 6.5 months
    r = c.post("/v1/breedings", json={"dam_id": young_ewe["id"], "mating_date": d(-1)}, headers=AR)
    assert r.status_code == 422 and "8 أشهر" in r.json["detail"]
    ewe = add(c, "E2", sex="female", date_of_birth=years_ago(2))
    young_ram = add(c, "R1", sex="male", date_of_birth=years_ago(2))
    r = mate(c, ewe, young_ram, when=-1)
    assert r.status_code == 422 and "4 years" in r.json["detail"]
    old_ram = add(c, "R2", sex="male", date_of_birth=years_ago(5))
    assert mate(c, ewe, old_ram, when=-1).status_code == 201
    heifer = add(c, "C1", species="cattle", sex="female", date_of_birth=d(-300))  # under a year
    assert mate(c, heifer, when=-1).status_code == 422
    # unknown age: not checked
    assert mate(c, add(c, "C2", species="cattle", sex="female"), when=-1).status_code == 201


def test_birds_are_not_mated(make_client):
    c = farm_client(make_client)
    hen = add(c, "H1", species="chicken", sex="female")
    r = c.post("/v1/breedings", json={"dam_id": hen["id"], "mating_date": d(-1)}, headers=AR)
    assert r.status_code == 422 and "دجاج" in r.json["detail"] and "chicken" not in r.json["detail"]


def test_birth_must_fit_the_pregnancy(make_client):
    c = farm_client(make_client)
    ewe = add(c, "E1", sex="female", date_of_birth=years_ago(3))
    b = mate(c, ewe, when=-200).json  # 200 days > 5 months 10 days
    r = c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(0), "offspring": [{"sex": "male"}]},
               headers=AR)
    assert r.status_code == 422 and "يرجى التحقّق من التواريخ" in r.json["detail"] and "5 أشهر و10 أيام" in r.json["detail"]
    too_soon = c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(-150), "offspring": [{"sex": "male"}]})
    assert too_soon.status_code == 422  # 50 days after the mating
    many = c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(-50), "offspring": [{"sex": "male"}] * 6})
    assert many.status_code == 422 and "at most 5" in many.json["detail"]
    assert c.post(f"/v1/breedings/{b['id']}/births",
                  json={"birth_date": d(-50), "offspring": [{"sex": "male"}] * 2}).status_code == 201


def test_cattle_pregnancy_is_9_months_10_days(make_client):
    c = farm_client(make_client)
    cow = add(c, "C1", species="cattle", sex="female", date_of_birth=years_ago(4))
    b = mate(c, cow, when=-300).json
    assert c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(0), "offspring": [{"sex": "male"}]}).status_code == 422
    assert c.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": d(-20), "offspring": [{"sex": "male"}]}).status_code == 201


def test_impossible_mating_dates(make_client):
    c = farm_client(make_client)
    ewe = add(c, "E1", sex="female", date_of_birth=years_ago(2))
    assert mate(c, ewe, when=3).status_code == 422  # future
    assert mate(c, ewe, when=-900).status_code == 422  # before she was born
    assert mate(c, ewe, when=-10, expected_birth_date=d(400)).status_code == 422  # outside the pregnancy
    assert mate(c, ewe, when=-10, pregnancy_status="confirmed", pregnancy_confirmed_date=d(-20)).status_code == 422


# ------------------------------------------------------------------ miscarriage

def test_miscarriage_needs_a_recent_date_and_a_reason(make_client):
    c = farm_client(make_client)
    ewe = add(c, "E1", sex="female", date_of_birth=years_ago(2))
    b = mate(c, ewe, when=-60).json
    url = f"/v1/breedings/{b['id']}"
    assert c.patch(url, json={"pregnancy_status": "aborted"}).status_code == 422
    assert c.patch(url, json={"pregnancy_status": "aborted", "miscarriage_date": d(-20),
                              "miscarriage_reason": "Fall"}).status_code == 422  # more than 14 days ago
    assert c.patch(url, json={"pregnancy_status": "aborted", "miscarriage_date": d(1),
                              "miscarriage_reason": "Fall"}).status_code == 422  # future
    ok = c.patch(url, json={"pregnancy_status": "aborted", "miscarriage_date": d(-3), "miscarriage_reason": "Fall"})
    assert ok.status_code == 200 and ok.json["miscarriage_date"] == d(-3) and ok.json["miscarriage_reason"] == "Fall"
    # a birth cannot be recorded on it, and a new mating after it is fine
    assert c.post(f"{url}/births", json={"birth_date": d(0), "offspring": [{"sex": "male"}]}).status_code == 409
    assert mate(c, ewe, when=-1).status_code == 201
    # a mating dated while she was carrying that pregnancy is refused
    assert mate(c, ewe, when=-30).status_code == 409


# ------------------------------------------------------------------ expenses carried by animals

def test_an_expense_with_no_animal_is_shared_by_the_farm_or_the_barn(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a = add(c, "S1", barn_id=fold["id"], purchase_price=100)
    b = add(c, "S2", purchase_price=100)
    farm = expense(c, 100, "utilities")
    assert farm["whole_farm"] and sorted(farm["animal_ids"]) == sorted([a["id"], b["id"]]) and farm["share"] == 50
    barn = expense(c, 30, "veterinary", barn_id=fold["id"])
    assert barn["whole_barn"] and barn["animal_ids"] == [a["id"]]
    card = c.get(f"/v1/animals/{a['id']}/costs").json
    assert (card["shared_total"], card["direct_total"], card["total_cost"]) == (50, 30, 180)
    bilan = c.get("/v1/finance/bilan").json
    assert bilan["herd_value"] == 330 and bilan["profit"] == round(330 - 200 - 130, 2)
    # editing the amount keeps the animals it was shared by
    assert c.patch(f"/v1/transactions/{farm['id']}", json={"amount": 120}).json["animal_ids"] == farm["animal_ids"]


def test_feed_is_shared_by_age(make_client):
    c = farm_client(make_client)
    lamb = add(c, "L1", date_of_birth=d(-90))      # 3 months: 0.5
    yearling = add(c, "Y1", date_of_birth=d(-270))  # 9 months: 1
    ewe = add(c, "E1", date_of_birth=years_ago(3))  # 3 years: 1.5
    feed = expense(c, 300, "feed")
    assert feed["weights"] == [0.5, 1.0, 1.5] and feed["share"] is None
    parts = {x["id"]: c.get(f"/v1/animals/{x['id']}/costs").json["expenses_total"] for x in (lamb, yearling, ewe)}
    assert parts == {lamb["id"]: 50, yearling["id"]: 100, ewe["id"]: 150}
    # other expenses stay equal
    assert expense(c, 300, "utilities")["share"] == 100


def test_entries_of_one_barn(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold"}).json
    a = add(c, "S1", barn_id=fold["id"])
    add(c, "S2")
    in_barn = expense(c, 10, "veterinary", animal_ids=[a["id"]])
    expense(c, 20, "veterinary", barn_id=fold["id"])
    other = expense(c, 30, "utilities", animal_ids=[])  # whole farm: carried by S1 too
    elsewhere = c.post("/v1/transactions", json={"type": "income", "category": "other_income", "amount": 5,
                                                 "date": d(0)}).json
    ids = {t["id"] for t in c.get(f"/v1/transactions?barn_id={fold['id']}").json}
    assert in_barn["id"] in ids and other["id"] in ids and elsewhere["id"] not in ids and len(ids) == 3


# ------------------------------------------------------------------ messages

def test_validation_message_is_one_translated_sentence(make_client):
    c = farm_client(make_client)
    r = c.post("/v1/animals", json={"species": "sheep", "sex": "female", "date_of_birth": d(5)}, headers=AR)
    assert r.status_code == 422
    assert r.json["message"] == "تاريخ الميلاد: لا يمكن أن يكون تاريخ الميلاد في المستقبل"
    en = c.post("/v1/animals", json={"species": "sheep", "sex": "female", "date_of_birth": d(5)})
    assert en.json["message"] == "Date of birth: The date of birth cannot be in the future"


def test_barn_message_says_what_to_do(make_client):
    c = farm_client(make_client)
    fold = c.post("/v1/barns", json={"name": "Fold", "species_list": ["goat"]}).json
    r = c.post("/v1/animals", json={"species": "horse", "sex": "male", "barn_id": fold["id"]}, headers=AR)
    assert r.json["detail"] == ("الحظيرة 'Fold' مخصّصة لـ ماعز فقط وليست لـ خيول. تحقّق من نوع الحيوان، أو عدّل الحظيرة "
                                "لتقبل خيول، أو اختر حظيرة أخرى أو أنشئ حظيرة جديدة")


def test_every_message_the_api_writes_is_translated():
    """Each text given to ApiError / ValueError in app/ has an Arabic (and French) translation."""
    from app.i18n import translate_text

    missing = []
    for path in pathlib.Path("app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            name = getattr(node, "func", None)
            name = getattr(name, "id", getattr(name, "attr", None))
            if not isinstance(node, ast.Call) or name not in ("ApiError", "ValueError", "_bad"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    text = arg.value
                elif isinstance(arg, ast.JoinedStr):
                    text = "".join(v.value if isinstance(v, ast.Constant) else "7" for v in arg.values)
                else:
                    continue
                for lang in ("ar", "fr"):
                    if translate_text(text, lang) == text.removeprefix("Value error, "):
                        missing.append(f"{path}:{node.lineno} [{lang}] {text}")
    allowed = {"Unsupported filter operator", "Wrong code. 7 attempt7 left"}
    missing = [m for m in missing if not any(a in m for a in allowed)]
    assert not missing, "\n".join(missing)
