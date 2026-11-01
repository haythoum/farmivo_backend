import io
from datetime import date, timedelta


def iso(days=0):
    return (date.today() + timedelta(days=days)).isoformat()


def test_healthz(client):
    assert client.get("/healthz").json == {"status": "ok"}


def test_requires_auth():
    from app.main import create_app
    r = create_app().test_client().get("/v1/animals")
    assert r.status_code == 401 and r.json == {"detail": "Missing bearer token"}


def test_unknown_route_is_json_404(client):
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json == {"detail": "Not Found"}


def test_animal_crud_and_duplicate_tag(client, cow):
    assert cow["age_label"]
    assert client.post("/v1/animals", json={"ear_tag": "C1", "species": "cattle", "sex": "male"}).status_code == 409
    r = client.patch(f"/v1/animals/{cow['id']}", json={"breed": "Holstein"})
    assert r.json["breed"] == "Holstein"
    assert [a["id"] for a in client.get("/v1/animals?q=bel").json] == [cow["id"]]
    assert client.delete(f"/v1/animals/{cow['id']}").status_code == 204
    assert client.get(f"/v1/animals/{cow['id']}").status_code == 404


def test_future_dob_rejected(client):
    r = client.post("/v1/animals", json={"ear_tag": "X", "species": "sheep", "sex": "male", "date_of_birth": iso(5)})
    assert r.status_code == 422


def test_vaccination_creates_reminder_and_dashboard(client, cow):
    r = client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD",
                                              "date_given": iso(-300), "next_due_date": iso(3)})
    assert r.status_code == 201
    reminders = client.get("/v1/reminders").json
    assert len(reminders) == 1 and reminders[0]["days_until"] == 3
    dash = client.get("/v1/dashboard").json
    assert dash["animals"]["total"] == 1
    assert dash["health"]["upcoming_vaccinations_count"] == 1
    client.delete(f"/v1/vaccinations/{r.json['id']}")
    assert client.get("/v1/reminders").json == []


def test_run_reminders_pushes_once(client, cow, repo, notifier):
    client.post("/v1/devices", json={"token": "t" * 20, "platform": "android"})
    client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD",
                                          "date_given": iso(-10), "next_due_date": iso(1)})
    from app.services.reminders import run_due_reminders
    assert run_due_reminders(repo, notifier)["notified"] == 1
    assert run_due_reminders(repo, notifier)["notified"] == 0
    assert len(notifier.sent) == 1
    assert len(client.get("/v1/notifications").json) == 1


def test_breeding_and_birth(client, cow):
    bull = client.post("/v1/animals", json={"ear_tag": "B1", "species": "cattle", "sex": "male"}).json
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "sire_id": bull["id"], "mating_date": iso(-10)}).json
    assert b["expected_birth_date"] == iso(-10 + 283)
    r = client.post(f"/v1/breedings/{b['id']}/births",
                    json={"birth_date": iso(), "offspring": [{"ear_tag": "C2", "sex": "female", "birth_weight_kg": 35}]})
    assert r.status_code == 201
    calf = r.json["offspring"][0]
    assert calf["mother_id"] == cow["id"] and calf["origin"] == "born_on_farm"
    assert r.json["breeding"]["pregnancy_status"] == "delivered"
    fam = client.get(f"/v1/animals/{cow['id']}/family").json
    assert [a["id"] for a in fam["offspring"]] == [calf["id"]]
    assert client.post(f"/v1/breedings/{b['id']}/births",
                       json={"birth_date": iso(), "offspring": [{"ear_tag": "C3", "sex": "male"}]}).status_code == 409


def test_growth_and_production(client, cow):
    for d, w in ((-20, 100), (-10, 120), (0, 140)):
        assert client.post("/v1/weights", json={"animal_id": cow["id"], "date": iso(d), "weight_kg": w}).status_code == 201
    g = client.get(f"/v1/animals/{cow['id']}/growth").json
    assert g["total_gain_kg"] == 40 and g["latest_weight_kg"] == 140
    client.post("/v1/production", json={"animal_id": cow["id"], "date": iso(-1), "product": "milk", "quantity": 20})
    client.post("/v1/production", json={"animal_id": cow["id"], "date": iso(), "product": "milk", "quantity": 22})
    s = client.get("/v1/production/summary?product=milk").json
    assert s["total"] == 42 and s["unit"] == "liters"


def test_sale_creates_income_and_finance_summary(client, cow):
    r = client.post(f"/v1/animals/{cow['id']}/status", json={"status": "sold", "sale_price": 900, "buyer": "Joe"})
    assert r.json["status"] == "sold"
    client.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 100, "date": iso()})
    s = client.get("/v1/finance/summary").json
    assert s["income"] == 900 and s["expenses"] == 100 and s["net"] == 800


def test_photo_upload(client, cow):
    r = client.post(f"/v1/animals/{cow['id']}/photo", data={"file": (io.BytesIO(b"\xff\xd8data"), "a.jpg", "image/jpeg")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["photo_url"].startswith("https://")
    r = client.post(f"/v1/animals/{cow['id']}/photo", data={"file": (io.BytesIO(b"x"), "a.txt", "text/plain")}, content_type="multipart/form-data")
    assert r.status_code == 415


def test_reports_csv(client, cow):
    r = client.get("/v1/reports/herd?format=csv")
    assert r.status_code == 200 and "C1" in r.get_data(as_text=True)


def test_validation_errors_use_detail(client):
    r = client.post("/v1/animals", json={"species": "cattle"})
    assert r.status_code == 422 and isinstance(r.json["detail"], list)
    assert client.get("/v1/animals?limit=0").status_code == 422
    assert client.get("/v1/production/summary").status_code == 422  # product is required
    assert client.get("/v1/reports/nope").status_code == 422


def test_cron_secret_required(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    assert client.post("/v1/internal/reminders/run").status_code == 403
    r = client.post("/v1/internal/reminders/run", headers={"X-Cron-Secret": "s3cret"})
    assert r.status_code == 200


def test_photo_served_through_api():
    from app.main import create_app

    class Store:
        def read(self, file_id):
            return (b"img", "image/png") if file_id == "ok" else None

    c = create_app(overrides={"photo_store": Store()}).test_client()
    r = c.get("/v1/photos/ok")
    assert r.status_code == 200 and r.data == b"img" and r.mimetype == "image/png"
    assert c.get("/v1/photos/missing").status_code == 404


def test_farm_address_roundtrip(client):
    r = client.patch("/v1/farm", json={"name": "Green Valley", "address": "Route de Mateur, Bizerte"})
    assert r.status_code == 200 and r.json["address"] == "Route de Mateur, Bizerte"
    assert client.get("/v1/farm").json["address"] == "Route de Mateur, Bizerte"
    assert client.patch("/v1/farm", json={"address": "x" * 201}).status_code == 422


def test_delete_sire_keeps_breeding(client, cow):
    bull = client.post("/v1/animals", json={"ear_tag": "B9", "species": "cattle", "sex": "male"}).json
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "sire_id": bull["id"], "mating_date": iso(-5)}).json
    assert client.delete(f"/v1/animals/{bull['id']}").status_code == 204
    kept = client.get(f"/v1/breedings/{b['id']}").json
    assert kept["sire_id"] is None and kept["dam_id"] == cow["id"]
