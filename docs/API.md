# Farmivo API contract (v1)

Base URL: `https://<host>/v1` (local: `flask --app app.main run --port 8000` → `http://localhost:8000/v1`). JSON everywhere, except the photo upload (multipart) and CSV reports.
This file is the reference for the contract; the backend serves no auto-generated docs page.

## Conventions

- **Auth**: every `/v1` endpoint requires `Authorization: Bearer <Firebase ID token>`. Mobile apps sign in with Firebase Auth (email/password; Google optional) and send a fresh ID token on each request (the Firebase SDK refreshes it; call `getIdToken` / `getIDToken` per request). `401` = missing/invalid token: refresh the token once, retry once, otherwise sign the user out.
- **Farm scoping**: each user is automatically given one farm on first request. There is no farm id in URLs.
- **Dates**: `YYYY-MM-DD` (e.g. `2026-10-31`). Timestamps (`created_at`, `updated_at`): ISO-8601 UTC strings.
- **IDs**: opaque strings.
- **Nulls**: optional fields may be `null` or omitted on input. On `PATCH` only send fields to change; send `null` explicitly to clear a nullable field.
- **Errors**: JSON `{"detail": "message"}` for 4xx (`404` not found, `409` conflict such as duplicate ear tag, `413`/`415` photo problems). Validation errors are `422` with `detail` = array of `{"loc": [...], "msg": "...", "type": "..."}`.
- **Unknown fields are rejected** (`422`) on input bodies.
- **Lists** return a bare JSON array, newest first unless stated.

## Enums

| Name | Values |
|---|---|
| species | `cattle` `sheep` `goat` `pig` `horse` `chicken` `duck` `rabbit` `other` |
| sex | `male` `female` |
| animal status | `active` `sick` `quarantine` `sold` `deceased` (on the farm = active, sick, quarantine) |
| origin | `born_on_farm` `purchased` `other` |
| pregnancy_status | `pending` `confirmed` `not_pregnant` `delivered` `aborted` |
| mating method | `natural` `artificial_insemination` |
| product | `milk` `eggs` `wool` `meat` `other` (default unit: liters, count, kg, kg, units) |
| transaction type | `income` `expense` |
| reminder source_type | `vaccination` `vet_visit` `birth` `custom` |

Suggested finance categories (free text, but offer these in the UI): income: `animal_sale`, `milk_sale`, `egg_sale`, `other_income`; expense: `feed`, `veterinary`, `medication`, `labor`, `equipment`, `purchase_animal`, `utilities`, `other_expense`.

## Farm & devices

| Method & path | Body | Response |
|---|---|---|
| `GET /farm` | | Farm |
| `PATCH /farm` | `{name?, currency? (3 letters), country?, address? (max 200)}` | Farm |
| `POST /devices` | `{token, platform: "android"\|"ios"}` (FCM token) | `204` |
| `DELETE /devices?token=...` | | `204` (call on sign-out) |

Farm: `{id, name, currency, country, address, owner_uid, created_at, updated_at}`. Default name "My Farm", currency "USD".
Call `POST /devices` after login and whenever the FCM token refreshes.

## Animals

Animal (response):
```json
{
  "id": "…", "ear_tag": "CR-0001", "name": "Bella", "species": "cattle", "breed": "Holstein",
  "sex": "female", "date_of_birth": "2022-03-14", "date_added": "2023-01-10",
  "origin": "purchased", "mother_id": null, "father_id": null, "notes": null,
  "status": "active", "status_date": null, "photo_url": "https://…",
  "age_days": 1692, "age_months": 55, "age_label": "4y 7m",
  "created_at": "…", "updated_at": "…"
}
```
`age_*` are computed by the server (null if no `date_of_birth`).

- `GET /animals?status=&species=&sex=&q=&limit=` → `[Animal]` sorted by ear tag. `status` accepts any animal status or `on_farm`. `q` searches ear tag, name, breed (case-insensitive).
- `POST /animals` → `201 Animal`. Body: `{ear_tag (required, unique per farm), species (required), sex (required), name?, breed?, date_of_birth?, date_added? (default today), origin? (default purchased), status? (default active), photo_url?, mother_id? (must be a female animal), father_id? (must be a male animal), notes?}`. `409` if the ear tag is taken. `date_of_birth` cannot be in the future.
- `GET /animals/{id}` → Animal
- `PATCH /animals/{id}` → Animal. Same fields as create except `status`/`photo_url` (use the endpoints below). `409` on duplicate ear tag.
- `POST /animals/{id}/status` → Animal. Body: `{status, date? (default today), sale_price?, buyer?, notes?}`. Marking `sold` with `sale_price` also creates an `animal_sale` income transaction. Marking `sold` or `deceased` closes the animal's pending reminders.
- `POST /animals/{id}/photo` → Animal. `multipart/form-data`, field name `file`, JPEG/PNG/WebP, max 5 MB (compress/resize to ~1600px on device). `photo_url` in the response is a public URL (`/v1/photos/{id}`, served by the API from GridFS or MinIO) that image loaders can fetch without an auth header.
- `DELETE /animals/{id}` → `204`. Deletes the animal and all its health, weight, production, feeding and breeding records.
- `GET /animals/{id}/family` → `{animal, mother, father, siblings: [Animal], offspring: [Animal]}` (mother/father may be null).
- `GET /animals/{id}/growth` → `{animal_id, points: [{date, weight_kg}] (ascending), latest_weight_kg, total_gain_kg, average_daily_gain_kg}` (aggregates null when not computable).

## Health & vaccination

All record endpoints below support: `GET ""` (list, filters `animal_id`, `date_from`, `date_to`, `limit` ≤ 1000, sorted by the date field, newest first), `POST ""` (`201`), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (`204`). Every record has `id`, `created_at`, `updated_at`. `404` if `animal_id` doesn't exist.

| Resource | Path | Fields (required in bold) | Date filter field |
|---|---|---|---|
| Vaccinations | `/vaccinations` | **animal_id**, **vaccine_name**, **date_given**, next_due_date, batch_number, administered_by, notes | `date_given` |
| Treatments | `/treatments` | **animal_id**, **name**, **start_date**, medication, dosage, end_date, withdrawal_end_date, administered_by, notes | `start_date` |
| Vet visits | `/vet-visits` | **animal_id**, **visit_date**, **reason**, vet_name, diagnosis, notes, follow_up_date | `visit_date` |
| Illnesses | `/illnesses` | **animal_id**, **condition**, **start_date**, recovery_date, symptoms, notes. Response also has `status`: `ongoing` (no recovery_date) or `recovered` | `start_date` |

`next_due_date` must not be before `date_given`.

### Automatic reminders
Setting `next_due_date` on a vaccination, `follow_up_date` on a vet visit, or an expected birth date on an active pregnancy automatically creates a reminder; changing/removing the date updates/removes it. The server pushes a notification (FCM) and stores an in-app notification when a reminder is 7 days away, 1 day away, due today, and overdue.

- `GET /reminders?status=pending|done|all (default pending)&within_days=&animal_id=&source_type=` → `[Reminder]` ascending by due date (overdue first). `within_days=30` includes overdue.
- `POST /reminders` `{title, due_date, animal_id?}` → `201 Reminder` (custom reminder)
- `POST /reminders/{id}/done` → Reminder
- `DELETE /reminders/{id}` → `204`

Reminder: `{id, source_type, source_id, animal_id, title, due_date, status, days_until}` (`days_until` negative = overdue).

## Breeding & reproduction

Resource `/breedings` (same list/get/patch/delete conventions; date filter `mating_date`):

Breeding: `{id, dam_id, sire_id, sire_note, mating_date, method, pregnancy_status, pregnancy_confirmed_date, expected_birth_date, actual_birth_date, offspring_ids: [], notes}`.
Create requires `dam_id` (female) and `mating_date`; `sire_id` (male) optional, `sire_note` for external sire / semen straw. If `expected_birth_date` is omitted the server fills it from the species' typical gestation (cattle 283, sheep 147, goat 150, pig 114, horse 340, rabbit 31 days; null for other species). `pregnancy_status` defaults to `pending`.

- `POST /breedings/{id}/births` → `201 {breeding, offspring: [Animal]}`. Body: `{birth_date, offspring: [{ear_tag, sex, name?, birth_weight_kg?, stillborn? (default false)}] (1–20), notes?}`. Creates the offspring as animals (species/breed of the dam, `origin=born_on_farm`, parents linked, stillborn → status `deceased`), records birth weights, sets the pregnancy to `delivered`. `409` if an ear tag is taken or a birth was already recorded.
- Parent/family history: `GET /animals/{id}/family`.

## Growth & production

- Weights `/weights`: **animal_id**, **date**, **weight_kg** (>0), notes. Filter by `animal_id`. Chart data: `GET /animals/{id}/growth`.
- Production `/production`: `animal_id?` (omit for herd/flock-level), **date**, **product**, **quantity** (≥0), `unit?` (defaults by product), notes.
- `GET /production/summary?product=milk&date_from=&date_to=&animal_id=` → `{product, unit, date_from, date_to, total, days_with_records, average_per_record_day, daily: [{date, total}]}`. Default window: last 30 days.
- Feeding `/feedings`: `animal_id?`, `group_name?`, **date**, **feed_type**, **quantity_kg** (>0), notes.

## Finance

- Transactions `/transactions`: **type**, **category**, **amount** (>0), **date**, description, animal_id. (Filters as above, date field `date`.)
- `GET /finance/summary?date_from=&date_to=` → `{date_from, date_to, currency, income, expenses, net, income_by_category: {cat: amount}, expenses_by_category: {…}, monthly: [{month: "YYYY-MM", income, expenses}]}`. Default window: last 30 days.

## Dashboard

`GET /dashboard?period_days=30&upcoming_days=30`
```json
{
  "generated_at": "…", "period_days": 30, "period_from": "2026-10-02", "period_to": "2026-10-31",
  "animals": {"total": 42, "total_all_time": 51, "by_species": {"cattle": 30, "sheep": 12},
              "by_sex": {"female": 28, "male": 14}, "by_status": {"active": 40, "sick": 2, "sold": 6, "deceased": 3}},
  "movements": {"births": 3, "deaths": 1, "sales": 2, "purchases": 0},
  "health": {"upcoming_vaccinations": [{"reminder_id","animal_id","animal_label","title","due_date","days_until"}],
             "upcoming_vaccinations_count": 4, "overdue_vaccinations_count": 1,
             "sick_animals": 2, "ongoing_illnesses": 2},
  "breeding": {"pregnant_count": 5, "due_soon": [{"breeding_id","dam_id","dam_label","expected_birth_date","days_until"}]},
  "finance": {"currency": "USD", "income": 1200.0, "expenses": 800.0, "net": 400.0},
  "unread_notifications": 3
}
```
`animals.total` counts animals currently on the farm; `by_status` covers all animals ever added. Maps may be empty.

## Notifications

- `GET /notifications?unread_only=false&limit=50` → `[{id, title, body, type, animal_id, reminder_id, read, created_at}]` newest first
- `POST /notifications/{id}/read` → Notification; `POST /notifications/read-all` → `204`; `DELETE /notifications/{id}` → `204`

Push payload (FCM): `notification{title, body}` + data `{type, animal_id?, reminder_id?}` — open the animal screen (or Reminders) when tapped.

## Reports

`GET /reports/{kind}?format=json|csv&date_from=&date_to=` with `kind` = `herd` | `vaccinations` | `financial` | `production` (default range last 90 days; `herd` ignores dates).
JSON: `{kind, date_from, date_to, columns: [...], rows: [{...}]}`. CSV: `text/csv` attachment — download and hand to the system share sheet.

## Health check

`GET /healthz` (no auth, not under `/v1`) → `{"status":"ok"}`.
