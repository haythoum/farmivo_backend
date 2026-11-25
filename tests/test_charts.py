"""Dashboard charts and key figures (GET /v1/dashboard/charts)."""
from __future__ import annotations

from datetime import date, timedelta

from app import insights
from tests.test_nov14 import add, farm_client
from tests.test_nov21 import _worker


def test_month_helpers():
    assert insights.month_start(date(2026, 1, 15), 1) == date(2025, 12, 1)
    assert insights.month_start(date(2026, 3, 31), -1) == date(2026, 4, 1)
    assert insights.month_end(date(2026, 2, 1)) == date(2026, 2, 28)
    assert insights.day("") is None and insights.day("bad") is None and insights.day("2026-05-04T10:00") == date(2026, 5, 4)
    assert insights.pct(3, 0) is None and insights.pct(1, 8) == 12.5


def test_average_daily_gain():
    rows = [{"animal_id": "a", "date": "2026-01-01", "weight_kg": 20}, {"animal_id": "a", "date": "2026-01-11", "weight_kg": 25},
            {"animal_id": "b", "date": "2026-01-01", "weight_kg": 30}, {"animal_id": "c", "date": "2026-01-01", "weight_kg": 9},
            {"animal_id": "c", "date": "2026-01-05", "weight_kg": 10}]
    assert insights.average_daily_gain(rows) == (0.375, 2)
    assert insights.average_daily_gain([]) == (None, 0)


def test_monthly_gain():
    rows = [{"animal_id": "a", "date": "2026-10-20", "weight_kg": 20}, {"animal_id": "a", "date": "2026-11-09", "weight_kg": 22},
            {"animal_id": "b", "date": "2026-11-01", "weight_kg": 30}, {"animal_id": "b", "date": "2026-11-11", "weight_kg": 31}]
    out = insights.monthly_gain(rows, ["2026-10", "2026-11"])
    assert out == [{"month": "2026-10", "gain_kg_day": None}, {"month": "2026-11", "gain_kg_day": 0.1}]


def test_charts_for_a_farm(make_client):
    c = farm_client(make_client)
    now = date.today()
    old = (now - timedelta(days=400)).isoformat()
    a = add(c, "S1", date_added=old, date_of_birth=old)
    add(c, "S2", date_added=now.isoformat(), origin="purchased")
    add(c, "L1", origin="born_on_farm", date_of_birth=now.isoformat(), date_added=now.isoformat())
    d = add(c, "S3", date_added=old)
    assert c.post(f"/v1/animals/{d['id']}/status", json={"status": "deceased", "date": now.isoformat()}).status_code == 200
    c.post("/v1/weights", json={"animal_id": a["id"], "date": (now - timedelta(days=10)).isoformat(), "weight_kg": 40})
    c.post("/v1/weights", json={"animal_id": a["id"], "date": now.isoformat(), "weight_kg": 42})
    c.post("/v1/production", json={"date": now.isoformat(), "product": "milk", "quantity": 12})
    c.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 300, "date": now.isoformat()})

    r = c.get("/v1/dashboard/charts")
    assert r.status_code == 200, r.json
    j = r.json
    assert len(j["herd_trend"]) == 12 and j["herd_trend"][-1] == {"month": now.strftime("%Y-%m"), "animals": 3}
    assert j["herd_trend"][0]["animals"] == 2  # S1 and S3 were there a year ago
    m = j["movements"][-1]
    assert (m["births"], m["deaths"], m["purchases"]) == (1, 1, 1) and len(j["movements"]) == 6
    assert j["age_groups"]["under_6m"] == 1 and j["age_groups"]["over_2y"] == 0 and j["age_groups"]["1_2y"] == 1
    assert len(j["milk"]["days"]) == 14 and j["milk"]["days"][-1]["quantity"] == 12
    k = j["kpis"]
    assert k["animals"] == 3 and k["deaths_year"] == 1 and k["average_daily_gain_kg"] == 0.2
    assert k["this_month"]["milk"] == 12 and k["this_month"]["expenses"] == 300
    assert k["cost_per_animal_month"] == 100 and j["finance"]["months"][-1]["net"] == -300
    assert len(j["gain_months"]) == 6 and j["gain_months"][-1]["gain_kg_day"] == 0.2


def test_workers_get_no_money(make_client):
    owner = farm_client(make_client)
    w = _worker(make_client, owner)
    j = w.get("/v1/dashboard/charts").json
    assert j["finance"] is None and "cost_per_animal_month" not in j["kpis"] and "income" not in j["kpis"]["this_month"]
