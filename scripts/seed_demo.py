"""Fill a farm with demo data so the apps have something to show.

    python -m scripts.seed_demo --uid <Firebase user id>          # real database from .env
    python -m scripts.seed_demo --uid demo --memory               # dry run in memory

The Firebase user id is shown in the Firebase console under Authentication > Users ("User UID").
Everything goes through the normal API code, so the same validation and automatic reminders apply.
Nothing is written if the farm already has animals.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.main import create_app


def day(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def post(client, path: str, body: dict) -> dict:
    response = client.post(f"/v1/{path}", json=body)
    if response.status_code >= 300:
        raise SystemExit(f"POST /v1/{path} failed: {response.status_code} {response.json}")
    return response.json


def seed(client) -> None:
    if client.get("/v1/animals").json:
        print("This farm already has animals, nothing written.")
        return
    client.patch("/v1/farm", json={"name": "Green Valley Farm", "country": "Tunisia", "currency": "TND",
                                   "address": "Route de Mateur, Bizerte, Tunisia"})

    bella = post(client, "animals", {"ear_tag": "CR-0412", "name": "Bella", "species": "cattle", "breed": "Holstein",
                                     "sex": "female", "date_of_birth": day(-1700), "date_added": day(-1200)})
    thor = post(client, "animals", {"ear_tag": "CR-0301", "name": "Thor", "species": "cattle", "breed": "Holstein",
                                    "sex": "male", "date_of_birth": day(-2500), "date_added": day(-2000)})
    max_ = post(client, "animals", {"ear_tag": "SH-0217", "name": "Max", "species": "sheep", "sex": "male",
                                    "date_of_birth": day(-900)})
    luna = post(client, "animals", {"ear_tag": "GT-0098", "name": "Luna", "species": "goat", "sex": "female",
                                    "date_of_birth": day(-700)})

    post(client, "vaccinations", {"animal_id": bella["id"], "vaccine_name": "Foot-and-mouth booster",
                                  "date_given": day(-180), "next_due_date": day(1)})
    post(client, "vaccinations", {"animal_id": max_["id"], "vaccine_name": "Clostridial",
                                  "date_given": day(-90), "next_due_date": day(5)})
    post(client, "vaccinations", {"animal_id": luna["id"], "vaccine_name": "Rabies",
                                  "date_given": day(-365), "next_due_date": day(-2)})
    post(client, "treatments", {"animal_id": bella["id"], "name": "Antibiotic course",
                                "medication": "Oxytetracycline", "start_date": day(-3)})
    post(client, "vet-visits", {"animal_id": bella["id"], "visit_date": day(-7), "vet_name": "Dr. Haddad",
                                "reason": "Lameness check", "follow_up_date": day(7)})

    post(client, "breedings", {"dam_id": bella["id"], "sire_id": thor["id"], "mating_date": day(-30)})

    for offset, kg in ((-90, 520), (-60, 535), (-30, 550), (0, 565)):
        post(client, "weights", {"animal_id": bella["id"], "date": day(offset), "weight_kg": kg})
    for offset in range(-6, 1):
        post(client, "production", {"animal_id": bella["id"], "date": day(offset), "product": "milk",
                                    "quantity": 20 + offset % 3, "unit": "liters"})
    post(client, "feedings", {"group_name": "Dairy herd", "date": day(), "feed_type": "Alfalfa hay", "quantity_kg": 120})

    post(client, "transactions", {"type": "income", "category": "milk sales", "amount": 1240, "date": day(-4)})
    post(client, "transactions", {"type": "expense", "category": "feed", "amount": 850, "date": day(-2)})
    print("Demo data written: 4 animals, vaccinations, treatment, vet visit, breeding, weights, milk, feeding, finance.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uid", required=True, help="Firebase user id that owns the farm")
    parser.add_argument("--memory", action="store_true", help="use an in-memory database (dry run)")
    args = parser.parse_args()

    overrides: dict = {"uid": args.uid}
    if args.memory:
        from app.repository import InMemoryRepository
        from app.services.notifier import NullNotifier
        from app.services.photos import MemoryPhotoStore

        overrides.update(repo=InMemoryRepository(), notifier=NullNotifier(), photo_store=MemoryPhotoStore())
    seed(create_app(overrides=overrides).test_client())


if __name__ == "__main__":
    main()
