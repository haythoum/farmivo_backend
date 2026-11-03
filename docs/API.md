# Farmivo API contract (v1)

Base URL: `https://<host>/v1` (local: `flask --app app.main run --port 8000` → `http://localhost:8000/v1`). JSON everywhere, except the photo upload (multipart) and CSV reports.
This file is the reference for the contract; the backend serves no auto-generated docs page.

## Conventions

- **Auth**: every `/v1` endpoint requires `Authorization: Bearer <Firebase ID token>`. Mobile apps sign in with Firebase Auth (email/password; Google optional) and send a fresh ID token on each request (the Firebase SDK refreshes it; call `getIdToken` / `getIDToken` per request). `401` = missing/invalid token: refresh the token once, retry once, otherwise sign the user out.
- **Farm scoping**: a user belongs to at most one farm, as owner, manager, worker or viewer (see [Members & roles](#members--roles) and [ROLES_AND_MEMBERS.md](ROLES_AND_MEMBERS.md)). Nothing is created automatically: after sign-in the app calls `GET /me` and then creates a farm or asks to join one. Every farm endpoint uses the caller's farm; there is no farm id in URLs.
- **Membership and role errors** are `403` with a machine-readable `code` next to `detail`: `{"detail": "...", "code": "no_farm" | "pending" | "rejected" | "forbidden_role"}`. Route on `code`, show `detail`.
- **Dates**: `YYYY-MM-DD` (e.g. `2026-10-31`). Timestamps (`created_at`, `updated_at`): ISO-8601 UTC strings.
- **IDs**: opaque strings.
- **Nulls**: optional fields may be `null` or omitted on input. On `PATCH` only send fields to change; send `null` explicitly to clear a nullable field.
- **Errors**: JSON `{"detail": "message"}` for 4xx (`404` not found, `409` conflict such as duplicate ear tag, `413`/`415` photo problems). Validation errors are `422` with `detail` = array of `{"loc": [...], "msg": "...", "type": "..."}`.
- **Unknown fields are rejected** (`422`) on input bodies.
- **Language**: send `Accept-Language` (the app's language: `ar`, `fr` or `en`; regional forms like `fr-FR` and q-values work; anything else means English). Error `detail` texts, the `msg` of common validation errors, notification titles/bodies and server-made reminder titles come back in that language. Error `code` values never change, so route on `code`. The last language a user sent is remembered for their pushes and emails.
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

## Members & roles

These work **without** a farm (token only):

| Method & path | Body | Response |
|---|---|---|
| `GET /me` | | `200 Me` |
| `POST /me/verification/send` | | `200 {sent_to, resend_after_seconds: 60, expires_in_seconds: 900}`: emails a new 6-digit code (the previous one stops working). `429 too_soon` with `retry_after` (seconds) within 60 s of the last code, `429 too_many_codes` after 5 codes in an hour, `409 already_verified`, `400 no_email`, `502 email_failed` |
| `POST /me/verification/verify` | `{code}` (`"482715"`, spaces ignored) | `200 Me` with `email_verified: true`. `400 wrong_code` ("Wrong code. 4 attempts left"), `429 too_many_attempts` after 5 wrong tries (the code is burnt), `410 code_expired` (expired, burnt or never sent) |
| `POST /farms` | `{name (2-80), address (5-200), country?, currency? (3 letters, default USD)}` | `201 Me` (caller becomes **owner**). `403 email_unverified` before the code was confirmed. `409` if already active in or waiting for a farm |
| `POST /farms/join` | `{invite_code}` (e.g. `GVF-7K3P`; case, spaces and dash optional) | `200 Me` with `status: "pending"`. `403 email_unverified` before the code was confirmed. `404 "No farm with this code"`, `409` if already active in a farm. A pending request to another farm is replaced; a rejected one may be repeated |
| `DELETE /me/membership` | | `200 Me` (`status: "none"`): cancels a pending request or leaves the farm. `409 "Transfer ownership first"` for the owner |
| `DELETE /me` | | `204`: **deletes the account**. Removes the user's devices, `users/<uid>`, email code and membership or join request. An owner who is the only active member also deletes the whole farm (every record and the photos). Then the Firebase sign-in account is deleted (best effort, logged on failure). `409 owner_must_transfer` ("Transfer ownership before deleting your account") when the owner's farm has other active members: nothing is deleted |

`Me`: `{uid, email, status: "none" | "pending" | "active" | "rejected", role: "owner" | "manager" | "worker" | "viewer" | null (null unless active), farm: {id, name} | null, email_verified: bool}`.

`email_verified` is true once the emailed code was confirmed, or when Firebase already marks the email verified, or for accounts that are already active farm members (accounts from before verification). Apps show the code screen while it is false; see [ROLES_AND_MEMBERS.md](ROLES_AND_MEMBERS.md#email-verification-code).

All the errors above carry a `code` field, e.g. `{"detail": "Please wait 42 seconds before asking for a new code", "code": "too_soon", "retry_after": 42}`.

Member management (manager or owner; transfer: owner only):

| Method & path | Body | Response |
|---|---|---|
| `GET /farm/members` | | `[Member]`: pending requests first (oldest first), then active members (owner, managers, workers, viewers). Rejected requests are not listed |
| `POST /farm/members/{uid}/approve` | optional `{role: "manager" \| "worker" \| "viewer"}` (default `worker`) | `Member`. Pushes "Welcome to <farm>" to the person. `409` if not pending |
| `POST /farm/members/{uid}/reject` | | `Member` (`status: "rejected"`). Pushes "Request not accepted". `409` if not pending |
| `PATCH /farm/members/{uid}` | `{role: "manager" \| "worker" \| "viewer"}` | `Member`. `409` for the owner (use transfer) or a pending request |
| `DELETE /farm/members/{uid}` | | `204`. Removes a member or a pending request; the person then has `status: "none"`. `409` for the owner |
| `POST /farm/invite-code` | | `{invite_code}`: new code, the old one stops working |
| `POST /farm/transfer-ownership` | `{uid}` (an active member) | `Member` (the new owner). The previous owner becomes a manager. `409` for yourself or a non-active member |

`Member`: `{uid, email, name, role, status: "pending" | "active", requested_at, decided_at, decided_by}`. `404 "Member not found"` for an unknown uid.

A join request also stores a farm notification of type `join_request` ("Ali wants to join") and is pushed to the owner and managers only.

### Who may call what

| | viewer | worker | manager | owner |
|---|:-:|:-:|:-:|:-:|
| Read (GET) animals, health, breeding, growth, production, feeding, reminders, notifications, dashboard, herd/vaccination/production reports, farm | ✓ | ✓ | ✓ | ✓ |
| Mark notifications read (`/read`, `/read-all`) | ✓ | ✓ | ✓ | ✓ |
| Create and edit records (POST/PATCH): animals, photo, status, health, reminders, reminder done, breedings, births, weights, production, feedings; delete notifications | | ✓ | ✓ | ✓ |
| Delete records (any `DELETE` except notifications) | | | ✓ | ✓ |
| Finance: `/transactions`, `/finance/summary`, `/reports/financial`; dashboard `finance` (null for others) | | | ✓ | ✓ |
| Farm settings `PATCH /farm`, see `invite_code` in `GET /farm` | | | ✓ | ✓ |
| Members: list, approve, reject, change role, remove; rotate invite code | | | ✓ | ✓ |
| Transfer ownership | | | | ✓ |

The server enforces this on every request (`app/permissions.py`); a refused call is `403` with `code: "forbidden_role"`. Apps should also hide what the role cannot do.

### 403 codes

| `code` | When | What the app shows |
|---|---|---|
| `no_farm` | Signed in but not in a farm (new account, removed, left) | "Create a farm" / "Join a farm" screen |
| `pending` | Join request waiting for approval | Waiting screen with the farm name, "Cancel request" |
| `rejected` | Join request refused | Message, then create a farm or join another one |
| `forbidden_role` | The role may not call this route | `detail`, e.g. "Your role (worker) does not allow this" |
| `email_unverified` | `POST /farms` or `POST /farms/join` before the email code was confirmed | The "Enter the 6-digit code" screen |

## Farm & devices

| Method & path | Body | Response |
|---|---|---|
| `GET /farm` | | Farm |
| `PATCH /farm` | `{name?, currency? (3 letters), country?, address? (max 200)}` (manager or owner) | Farm |
| `POST /devices` | `{token, platform: "android"\|"ios", language?: "ar"\|"fr"\|"en"}` (FCM token) | `204`. Works without a farm, so a pending user receives the approval push. `language` is the language pushes to this phone use (default: the request's `Accept-Language`); send it again when the user changes the app language |
| `DELETE /devices?token=...` | | `204` (call on sign-out) |

Farm: `{id, name, currency, country, address, owner_uid, invite_code (null unless the caller is manager or owner), role (the caller's role), created_at, updated_at}`.
Call `POST /devices` after login and whenever the FCM token refreshes.

### Sign-up rules (enforced by the apps before they call Firebase)
Accounts are created with Firebase Auth, not by this API. The apps require a valid email, a password of at least 8 characters with a letter and a number, and a matching confirmation. After sign-up the user either creates a farm (`POST /farms`, farm name 2-80 characters, address 5-200, also checked by the API) or joins one with an invite code (`POST /farms/join`).

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
  "finance": {"currency": "USD", "income": 1200.0, "expenses": 800.0, "net": 400.0},  // null for workers and viewers
  "unread_notifications": 3
}
```
`animals.total` counts animals currently on the farm; `by_status` covers all animals ever added. Maps may be empty.

## Notifications

- `GET /notifications?unread_only=false&limit=50` → `[{id, title, body, type, animal_id, reminder_id, read, created_at}]` newest first. `title`/`body` are in the request's language. Workers and viewers don't see `join_request` notifications (and `read-all` doesn't touch them). Personal notifications (`membership_approved`, stored with `for_uid`) are seen only by that member. The `read` flag is shared by the farm.
- `POST /notifications/{id}/read` → Notification; `POST /notifications/read-all` → `204`; `DELETE /notifications/{id}` → `204`. A notification the caller may not see answers `404`.
- `join_request` notifications are marked read automatically once the request is approved, rejected, cancelled or removed (by anyone), so they don't stay unread for other managers.
- **When a push is tapped**, the app calls `POST /notifications/{data.notification_id}/read` (when the id is present), then opens the screen for `data.type`.

Push payload (FCM), in the recipient's language (phone `language`, else the user's last `Accept-Language`, else English):

```json
{
  "notification": {"title": "...", "body": "..."},
  "data": {"type": "join_request", "farm_id": "...", "notification_id": "...", "animal_id": "...", "reminder_id": "..."},
  "android": {"priority": "high", "notification": {"channel_id": "farmivo_members", "icon": "ic_notification", "color": "#1F6F6B"}},
  "apns": {"headers": {"apns-priority": "10"}, "payload": {"aps": {"sound": "default", "mutable-content": 1}}}
}
```

| `data.type` | Sent to | Android channel | Open when tapped |
|---|---|---|---|
| `join_request` | active owner and managers | `farmivo_members` | Members |
| `membership_approved` | the new member (stored as their personal notification, with `notification_id`) | `farmivo_members` | reload `GET /me` and route |
| `membership_rejected` | the requester (not a member: push only, **no** `notification_id`) | `farmivo_members` | reload `GET /me` and route |
| `vaccination` / `vet_visit` / `birth` / `custom` | all active members | `farmivo_reminders` | the animal (`animal_id`) or Reminders |

`data.notification_id` is the id of the stored notification for `join_request`, `membership_approved` and every reminder type. `data` values are strings; keys without a value are left out. The app must create both channels and ship the `ic_notification` drawable; otherwise Android falls back to the app icon.

## Reports

`GET /reports/{kind}?format=json|csv&date_from=&date_to=` with `kind` = `herd` | `vaccinations` | `financial` | `production` (default range last 90 days; `herd` ignores dates).
JSON: `{kind, date_from, date_to, columns: [...], rows: [{...}]}`. CSV: `text/csv` attachment — download and hand to the system share sheet.

## Health check

`GET /healthz` (no auth, not under `/v1`) → `{"status":"ok"}`.

## Public pages (no auth, not under `/v1`)

HTML pages for the stores and the apps' More screen, in English, French and Arabic (Arabic right to left). Language: `?lang=en|fr|ar`, else `Accept-Language`, else English.

| Path | Content |
|---|---|
| `GET /privacy` | Privacy policy (store "Privacy policy URL") |
| `GET /terms` | Terms of use |
| `GET /support` | 301 redirect to the QuadraLens product page https://quadralens.tn/product/farmivo/ (help and support) |
| `GET /delete-account` | How to delete the account in the app or by email, and what is deleted (Google Play "Delete account URL") |

**The texts are templates written for QuadraLens: the owner (ideally with a lawyer) must review them before release.** They live in `app/legal.py`; the layout is `app/templates/legal/page.html`.
