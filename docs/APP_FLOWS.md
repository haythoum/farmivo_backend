# How the apps work, call by call

This guide walks through every screen of the Android and iOS apps: what the user does, which calls the app makes, and what comes back. **Every response below was produced by running the real backend code** (in-memory database, `docs` tests setup), shortened where lists are long (`... (n more)`). IDs and timestamps differ on your system.

## 1. The two services the app talks to

| Service | Used for | Needs your server? |
|---|---|---|
| **Firebase Auth** | Create account, sign in, sign out, token refresh | No (Google) |
| **Farmivo API** (Flask, `https://YOUR_SERVER/v1/...`) | Everything else: animals, health, breeding, growth, finance, reports, notifications | Yes |
| **Firebase Cloud Messaging** | Delivers push notifications to the phone | No (Google) |

So **signing in can work while every data screen fails**: sign-in never touches your server. If the data screens fail, the problem is the API address or the server (see section 12).

Every API call carries `Authorization: Bearer <Firebase ID token>`. The backend verifies the token with Firebase, takes the user id (`uid`) from it, and finds that user's farm. That is why no URL contains a farm id.

> A new database is empty. Use `python -m scripts.seed_demo --uid <Firebase UID>` to load sample data (see DEVELOPMENT_GUIDE).

## 2. App start

1. The app reads the saved Firebase session. **Not signed in** goes to the Sign in screen.
2. **Signed in**: the app registers the phone for push (`POST /v1/devices`, works without a farm) and asks the server where the user stands with `GET /v1/me`. The answer decides the screen:

| `status` | Screen |
|---|---|
| `none` | Choose **Create a new farm** or **Join a farm** (section 3) |
| `pending` | "Waiting for approval from <farm>" with Cancel request / Sign out |
| `rejected` | "Your request was not accepted", then create a farm or join another |
| `active` | Main screen on the Dashboard; actions shown according to `role` |

3. On the main screen the app loads the animal list in the background (used by the "+" forms).

```http
GET /v1/me
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "uid": "uid-owner",
  "email": "rahma@greenvalley.farm",
  "status": "none",
  "role": null,
  "farm": null
}
```

Roles and who may do what: [ROLES_AND_MEMBERS.md](ROLES_AND_MEMBERS.md).

## 3. Create account, then create or join a farm

Screen fields: email, password, confirm password. Rules (checked in the app before anything is sent): email in a valid format, password at least 8 characters with a letter and a digit, both passwords equal. Errors appear under each field.

| Step | Call | Who answers |
|---|---|---|
| 1. Create the login | Firebase `createUserWithEmailAndPassword(email, password)` | Firebase |
| 2. Where do I stand? | `GET /v1/me` gives `status: "none"` | Farmivo API |
| 3a. **Create a new farm** (name 2-80, address 5-200) | `POST /v1/farms`: the user becomes the **owner** | Farmivo API |
| 3b. **Join a farm** (invite code from the farm's owner or manager) | `POST /v1/farms/join`: the request waits for approval | Farmivo API |
| 4. Open the Dashboard (3a) or the waiting screen (3b) | | |

Firebase failures are shown as: "This email already has an account", "Wrong email or password", weak password, "No connection", "Too many attempts".

### 3a. Create a new farm
```http
POST /v1/farms
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "name": "Green Valley Farm",
  "address": "Route de Mateur, Bizerte, Tunisia",
  "country": "Tunisia",
  "currency": "TND"
}
```
**Response `201`**
```json
{
  "uid": "uid-owner",
  "email": "rahma@greenvalley.farm",
  "status": "active",
  "role": "owner",
  "farm": {
    "id": "861598b06c784d80bd3994b068e6e56c",
    "name": "Green Valley Farm"
  }
}
```

### 3b. Join a farm
The invite code is shown to managers and the owner in Farm settings (section 6). Case, spaces and the dash do not matter.
```http
POST /v1/farms/join
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "invite_code": "GVF-X22Y"
}
```
**Response `200`**
```json
{
  "uid": "uid-ali",
  "email": "ali@example.com",
  "status": "pending",
  "role": null,
  "farm": {
    "id": "861598b06c784d80bd3994b068e6e56c",
    "name": "Green Valley Farm"
  }
}
```

While waiting, every farm call answers `403` with `code: "pending"`:
```http
GET /v1/animals
Authorization: Bearer <Firebase ID token>
```
**Response `403`**
```json
{
  "detail": "Your request to join Green Valley Farm is waiting for approval",
  "code": "pending"
}
```

Wrong code:
```http
POST /v1/farms/join
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "invite_code": "ZZZ-2222"
}
```
**Response `404`**
```json
{
  "detail": "No farm with this code"
}
```

### 3c. Approval (owner or manager, More > Members)
The owner and managers get a push "Ali wants to join" and see the request on top of the list:
```http
GET /v1/farm/members
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
[
  {
    "uid": "uid-ali",
    "email": "ali@example.com",
    "name": "Ali",
    "role": "worker",
    "status": "pending",
    "requested_at": "2026-11-01T11:46:53+00:00",
    "decided_at": null,
    "decided_by": null
  },
  {
    "uid": "uid-owner",
    "email": "rahma@greenvalley.farm",
    "name": "Rahma",
    "role": "owner",
    "status": "active",
    "requested_at": "2026-11-01T11:46:53+00:00",
    "decided_at": "2026-11-01T11:46:53+00:00",
    "decided_by": "uid-owner"
  }
]
```

```http
POST /v1/farm/members/uid-ali/approve
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "role": "worker"
}
```
**Response `200`**
```json
{
  "uid": "uid-ali",
  "email": "ali@example.com",
  "name": "Ali",
  "role": "worker",
  "status": "active",
  "requested_at": "2026-11-01T11:46:53+00:00",
  "decided_at": "2026-11-01T11:46:53+00:00",
  "decided_by": "uid-owner"
}
```

Ali gets a push "Welcome to Green Valley Farm"; his app calls `GET /v1/me` again:
```http
GET /v1/me
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "uid": "uid-ali",
  "email": "ali@example.com",
  "status": "active",
  "role": "worker",
  "farm": {
    "id": "861598b06c784d80bd3994b068e6e56c",
    "name": "Green Valley Farm"
  }
}
```

Reject instead: `POST /v1/farm/members/{uid}/reject`. Other member actions (change role, remove, new invite code, transfer ownership): [API.md](API.md#members--roles).

## 4. Sign in

Fields: email, password (both required, email must be valid).

1. Firebase `signInWithEmailAndPassword`. Wrong data fails here with "Wrong email or password"; nobody gets in without a valid Firebase account.
2. `GET /v1/me` decides the screen (section 2). Nothing is created automatically: an account without a farm sees the create-or-join screen, and a farm call answers `403 no_farm`:
```http
GET /v1/dashboard
Authorization: Bearer <Firebase ID token>
```
**Response `403`**
```json
{
  "detail": "You are not a member of a farm yet",
  "code": "no_farm"
}
```

## 5. Sign out (More > Sign out)

1. `DELETE /v1/devices?token=<push token>`: this phone stops receiving the farm's pushes.
2. Firebase `signOut()`.
3. Back to the Sign in screen.

Leaving the farm (not the same as signing out) is `DELETE /v1/me/membership`. The owner must transfer ownership first:
```http
DELETE /v1/me/membership
Authorization: Bearer <Firebase ID token>
```
**Response `409`**
```json
{
  "detail": "Transfer ownership first"
}
```

## 6. Farm settings (More > Farm settings)

Everyone can open it; only managers and the owner can save, and only they see the **invite code**. Fields: name, currency (3 letters), country, address. `role` is the caller's role.

```http
GET /v1/farm
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "id": "861598b06c784d80bd3994b068e6e56c",
  "created_at": "2026-11-01T11:46:53+00:00",
  "updated_at": "2026-11-01T11:46:53+00:00",
  "name": "Green Valley Farm",
  "currency": "TND",
  "country": "Tunisia",
  "address": "Route de Mateur, Bizerte, Tunisia",
  "owner_uid": "uid-owner",
  "invite_code": "GVF-X22Y",
  "role": "owner"
}
```

```http
PATCH /v1/farm
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "name": "Green Valley Farm",
  "address": "Route de Mateur km 4, Bizerte, Tunisia"
}
```
**Response `200`**
```json
{
  "id": "861598b06c784d80bd3994b068e6e56c",
  "created_at": "2026-11-01T11:46:53+00:00",
  "updated_at": "2026-11-01T11:46:53+00:00",
  "name": "Green Valley Farm",
  "currency": "TND",
  "country": "Tunisia",
  "address": "Route de Mateur km 4, Bizerte, Tunisia",
  "owner_uid": "uid-owner",
  "invite_code": "GVF-X22Y",
  "role": "owner"
}
```


## 7. Animals

### 7.1 Animals tab (list, search, filter)
Search box and chips call the list with `q` (search by name/tag) and `status`.
```http
GET /v1/animals?status=on_farm&q=bel
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
[
  {
    "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "created_at": "2026-10-31T20:37:31+00:00",
    "updated_at": "2026-10-31T20:37:31+00:00",
    "ear_tag": "CR-0412",
    "name": "Bella",
    "species": "cattle",
    "breed": "Holstein",
    "sex": "female",
    "date_of_birth": "2022-03-06",
    "date_added": "2023-07-19",
    "origin": "purchased",
    "mother_id": null,
    "father_id": null,
    "notes": null,
    "status": "active",
    "status_date": null,
    "photo_url": null,
    "age_days": 1700,
    "age_months": 55,
    "age_label": "4y 7m"
  }
]
```

### 7.2 Add animal (the + button)
Required: ear tag, species, sex. Optional: name, breed, date of birth, date added, mother, father, notes. The date of birth cannot be in the future; the ear tag must be unique in the farm.
```http
POST /v1/animals
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "ear_tag": "CR-0412",
  "name": "Bella",
  "species": "cattle",
  "breed": "Holstein",
  "sex": "female",
  "date_of_birth": "2022-03-06",
  "date_added": "2023-07-19"
}
```
**Response `201`**
```json
{
  "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "created_at": "2026-10-31T20:37:31+00:00",
  "updated_at": "2026-10-31T20:37:31+00:00",
  "ear_tag": "CR-0412",
  "name": "Bella",
  "species": "cattle",
  "breed": "Holstein",
  "sex": "female",
  "date_of_birth": "2022-03-06",
  "date_added": "2023-07-19",
  "origin": "purchased",
  "mother_id": null,
  "father_id": null,
  "notes": null,
  "status": "active",
  "status_date": null,
  "photo_url": null,
  "age_days": 1700,
  "age_months": 55,
  "age_label": "4y 7m"
}
```

Duplicate ear tag:
```http
POST /v1/animals
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "ear_tag": "CR-0412",
  "species": "cattle",
  "sex": "male"
}
```
**Response `409`**
```json
{
  "detail": "Ear tag 'CR-0412' is already used on this farm"
}
```

Invalid data (the app normally stops this before sending):
```http
POST /v1/animals
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "ear_tag": "",
  "species": "cattle",
  "sex": "female"
}
```
**Response `422`**
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": [
        "ear_tag"
      ],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {
        "min_length": 1
      }
    }
  ]
}
```

### 7.3 Animal profile
Tapping an animal opens its profile (`GET /v1/animals/{id}`), the Family tab (`GET /v1/animals/{id}/family`: mother, father, offspring), the Health tab and the Growth tab.
```http
GET /v1/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "created_at": "2026-10-31T20:37:31+00:00",
  "updated_at": "2026-10-31T20:37:31+00:00",
  "ear_tag": "CR-0412",
  "name": "Bella",
  "species": "cattle",
  "breed": "Holstein",
  "sex": "female",
  "date_of_birth": "2022-03-06",
  "date_added": "2023-07-19",
  "origin": "purchased",
  "mother_id": null,
  "father_id": null,
  "notes": null,
  "status": "active",
  "status_date": null,
  "photo_url": null,
  "age_days": 1700,
  "age_months": 55,
  "age_label": "4y 7m"
}
```

Edit uses `PATCH` with only the changed fields:
```http
PATCH /v1/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "breed": "Holstein-Friesian"
}
```
**Response `200`**
```json
{
  "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "created_at": "2026-10-31T20:37:31+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "ear_tag": "CR-0412",
  "name": "Bella",
  "species": "cattle",
  "breed": "Holstein-Friesian",
  "sex": "female",
  "date_of_birth": "2022-03-06",
  "date_added": "2023-07-19",
  "origin": "purchased",
  "mother_id": null,
  "father_id": null,
  "notes": null,
  "status": "active",
  "status_date": null,
  "photo_url": null,
  "age_days": 1700,
  "age_months": 55,
  "age_label": "4y 7m"
}
```

### 7.4 Photo
Tap the photo or **Photo**, pick an image (JPEG, PNG or WebP, max 5 MB). The app uploads it as multipart form data in the field `file`. The animal comes back with `photo_url`.
```http
POST /v1/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a/photo
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "created_at": "2026-10-31T20:37:31+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "ear_tag": "CR-0412",
  "name": "Bella",
  "species": "cattle",
  "breed": "Holstein-Friesian",
  "sex": "female",
  "date_of_birth": "2022-03-06",
  "date_added": "2023-07-19",
  "origin": "purchased",
  "mother_id": null,
  "father_id": null,
  "notes": null,
  "status": "active",
  "status_date": null,
  "photo_url": "https://storage.test/farms/09313bd5a801432bbb182a8b0d0f7707/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a/c69730b42fe0409c9602cb565c38403d.jpg",
  "age_days": 1700,
  "age_months": 55,
  "age_label": "4y 7m"
}
```

### 7.5 Change status (sold, died, ...)
`POST /v1/animals/{id}/status`. A **sold** animal with a sale price also creates an income entry in Finance automatically. See section 11.
```http
POST /v1/animals/283a276c7c9f462a93b2e1c5f7dd19d6/status
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "status": "sold",
  "sale_price": 2400,
  "buyer": "Ali Ben Salah"
}
```
**Response `200`**
```json
{
  "id": "283a276c7c9f462a93b2e1c5f7dd19d6",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "ear_tag": "CR-0301",
  "name": "Thor",
  "species": "cattle",
  "breed": null,
  "sex": "male",
  "date_of_birth": "2019-12-27",
  "date_added": "2026-10-31",
  "origin": "purchased",
  "mother_id": null,
  "father_id": null,
  "notes": null,
  "status": "sold",
  "status_date": "2026-10-31",
  "photo_url": null,
  "age_days": 2500,
  "age_months": 82,
  "age_label": "6y 10m"
}
```

### 7.6 Delete
`DELETE /v1/animals/{id}` returns `204` with no body.

## 8. Health

The Health tab has four lists: Vaccinations, Treatments, Vet visits, Illness. Each list is `GET /v1/<type>` (optionally `?animal_id=`). The **+** button creates a record, tapping a row edits it, long-press or the delete action removes it.

### 8.1 Vaccination and automatic reminders
When `next_due_date` is set, the server creates a reminder **by itself**. Editing the date moves the reminder, deleting the vaccination removes it. A daily job sends push notifications 7 days before, 1 day before, on the day, and when overdue.
```http
POST /v1/vaccinations
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "vaccine_name": "Foot-and-mouth booster",
  "date_given": "2026-05-04",
  "next_due_date": "2026-11-01"
}
```
**Response `201`**
```json
{
  "id": "d51a155c6578438bae9390a0cf989cca",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "vaccine_name": "Foot-and-mouth booster",
  "date_given": "2026-05-04",
  "next_due_date": "2026-11-01",
  "batch_number": null,
  "administered_by": null,
  "notes": null
}
```

```http
GET /v1/reminders
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
[
  {
    "id": "vacc_d51a155c6578438bae9390a0cf989cca",
    "created_at": "2026-10-31T20:37:32+00:00",
    "updated_at": "2026-10-31T20:37:32+00:00",
    "source_type": "vaccination",
    "source_id": "d51a155c6578438bae9390a0cf989cca",
    "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "title": "Vaccination due: Foot-and-mouth booster (Bella (CR-0412))",
    "due_date": "2026-11-01",
    "status": "pending",
    "days_until": 1
  }
]
```

### 8.2 Treatment
```http
POST /v1/treatments
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "name": "Antibiotic course",
  "medication": "Oxytetracycline",
  "start_date": "2026-10-28"
}
```
**Response `201`**
```json
{
  "id": "0fd1bf264bd7462b8cb2ce564ac5788e",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "name": "Antibiotic course",
  "medication": "Oxytetracycline",
  "dosage": null,
  "start_date": "2026-10-28",
  "end_date": null,
  "withdrawal_end_date": null,
  "administered_by": null,
  "notes": null
}
```

### 8.3 Vet visit
A `follow_up_date` also creates a reminder.
```http
POST /v1/vet-visits
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "visit_date": "2026-10-24",
  "vet_name": "Dr. Haddad",
  "reason": "Lameness check",
  "follow_up_date": "2026-11-07"
}
```
**Response `201`**
```json
{
  "id": "b5f283d1de2843eba3141f95304be917",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "visit_date": "2026-10-24",
  "vet_name": "Dr. Haddad",
  "reason": "Lameness check",
  "diagnosis": null,
  "notes": null,
  "follow_up_date": "2026-11-07"
}
```

### 8.4 Illness and recovery
```http
POST /v1/illnesses
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "condition": "Mastitis",
  "start_date": "2026-10-26",
  "symptoms": "Swollen udder"
}
```
**Response `201`**
```json
{
  "id": "e4e2afcd46e742b4ba2499409bf61b74",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "condition": "Mastitis",
  "start_date": "2026-10-26",
  "recovery_date": null,
  "symptoms": "Swollen udder",
  "notes": null,
  "status": "ongoing"
}
```

### 8.5 Delete a record
```http
DELETE /v1/vaccinations/d51a155c6578438bae9390a0cf989cca
Authorization: Bearer <Firebase ID token>
```
**Response `204`**
```json
(empty)
```


## 9. Breeding

1. **Record mating** (+): dam (female) and sire or a note for an external sire. The server calculates `expected_birth_date` from the species' gestation length and creates a birth reminder.
```http
POST /v1/breedings
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "dam_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "sire_id": "283a276c7c9f462a93b2e1c5f7dd19d6",
  "mating_date": "2026-10-01"
}
```
**Response `201`**
```json
{
  "id": "f62a8c11a8e74c309f3870bc81ef5741",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "dam_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "sire_id": "283a276c7c9f462a93b2e1c5f7dd19d6",
  "sire_note": null,
  "mating_date": "2026-10-01",
  "method": "natural",
  "pregnancy_status": "pending",
  "pregnancy_confirmed_date": null,
  "expected_birth_date": "2027-07-11",
  "notes": null,
  "actual_birth_date": null,
  "offspring_ids": []
}
```

2. **Record birth**: one or more offspring. The server creates each calf as a new animal (mother and father set, origin "born on farm"), marks the breeding "delivered", and can only be done once per breeding.
```http
POST /v1/breedings/f62a8c11a8e74c309f3870bc81ef5741/births
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "birth_date": "2026-10-31",
  "offspring": [
    {
      "ear_tag": "CR-0501",
      "sex": "female",
      "birth_weight_kg": 36
    }
  ]
}
```
**Response `201`**
```json
{
  "breeding": {
    "id": "f62a8c11a8e74c309f3870bc81ef5741",
    "created_at": "2026-10-31T20:37:32+00:00",
    "updated_at": "2026-10-31T20:37:32+00:00",
    "dam_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "sire_id": "283a276c7c9f462a93b2e1c5f7dd19d6",
    "sire_note": null,
    "mating_date": "2026-10-01",
    "method": "natural",
    "pregnancy_status": "delivered",
    "pregnancy_confirmed_date": null,
    "expected_birth_date": "2027-07-11",
    "notes": null,
    "actual_birth_date": "2026-10-31",
    "offspring_ids": [
      "8f555513a6674ef9861178b99e6227ee"
    ]
  },
  "offspring": [
    {
      "id": "8f555513a6674ef9861178b99e6227ee",
      "created_at": "2026-10-31T20:37:32+00:00",
      "updated_at": "2026-10-31T20:37:32+00:00",
      "ear_tag": "CR-0501",
      "name": null,
      "species": "cattle",
      "breed": "Holstein-Friesian",
      "sex": "female",
      "date_of_birth": "2026-10-31",
      "date_added": "2026-10-31",
      "origin": "born_on_farm",
      "mother_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
      "father_id": "283a276c7c9f462a93b2e1c5f7dd19d6",
      "notes": null,
      "status": "active",
      "status_date": null,
      "photo_url": null,
      "age_days": 0,
      "age_months": 0,
      "age_label": "0d"
    }
  ]
}
```

3. The mother's Family tab now lists the calf:
```http
GET /v1/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a/family
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "animal": {
    "id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "created_at": "2026-10-31T20:37:31+00:00",
    "updated_at": "2026-10-31T20:37:32+00:00",
    "ear_tag": "CR-0412",
    "name": "Bella",
    "species": "cattle",
    "breed": "Holstein-Friesian",
    "sex": "female",
    "date_of_birth": "2022-03-06",
    "date_added": "2023-07-19",
    "origin": "purchased",
    "mother_id": null,
    "father_id": null,
    "notes": null,
    "status": "active",
    "status_date": null,
    "photo_url": "https://storage.test/farms/09313bd5a801432bbb182a8b0d0f7707/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a/c69730b42fe0409c9602cb565c38403d.jpg",
    "age_days": 1700,
    "age_months": 55,
    "age_label": "4y 7m"
  },
  "mother": null,
  "father": null,
  "siblings": [],
  "offspring": [
    {
      "id": "8f555513a6674ef9861178b99e6227ee",
      "created_at": "2026-10-31T20:37:32+00:00",
      "updated_at": "2026-10-31T20:37:32+00:00",
      "ear_tag": "CR-0501",
      "name": null,
      "species": "cattle",
      "breed": "Holstein-Friesian",
      "sex": "female",
      "date_of_birth": "2026-10-31",
      "date_added": "2026-10-31",
      "origin": "born_on_farm",
      "mother_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
      "father_id": "283a276c7c9f462a93b2e1c5f7dd19d6",
      "notes": null,
      "status": "active",
      "status_date": null,
      "photo_url": null,
      "age_days": 0,
      "age_months": 0,
      "age_label": "0d"
    }
  ]
}
```


## 10. Growth and production

### 10.1 Weights
```http
POST /v1/weights
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "date": "2026-10-30",
  "weight_kg": 560
}
```
**Response `201`**
```json
{
  "id": "c6bc12209e04488989041d325a8c36fe",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "date": "2026-10-30",
  "weight_kg": 560.0,
  "notes": null
}
```

### 10.2 Growth chart (animal profile > Growth)
Gain and average daily gain are computed from the weight records:
```http
GET /v1/animals/e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a/growth
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "points": [
    {
      "date": "2026-09-01",
      "weight_kg": 520.0
    },
    {
      "date": "2026-10-01",
      "weight_kg": 540.0
    },
    {
      "date": "2026-10-30",
      "weight_kg": 560.0
    },
    "... (1 more)"
  ],
  "latest_weight_kg": 565.0,
  "total_gain_kg": 45.0,
  "average_daily_gain_kg": 0.75
}
```

### 10.3 Production (milk, eggs, wool, meat...)
```http
POST /v1/production
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "date": "2026-10-31",
  "product": "milk",
  "quantity": 22,
  "unit": "liters"
}
```
**Response `201`**
```json
{
  "id": "6b35b90a8b5d4d4093e4a08faaefe73b",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
  "date": "2026-10-31",
  "product": "milk",
  "quantity": 22.0,
  "unit": "liters",
  "notes": null
}
```

Summary for a product:
```http
GET /v1/production/summary?product=milk
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "product": "milk",
  "unit": "liters",
  "date_from": "2026-10-02",
  "date_to": "2026-10-31",
  "total": 42.0,
  "days_with_records": 2,
  "average_per_record_day": 21.0,
  "daily": [
    {
      "date": "2026-10-30",
      "total": 20.0
    },
    {
      "date": "2026-10-31",
      "total": 22.0
    }
  ]
}
```

### 10.4 Feeding
Per animal or per group:
```http
POST /v1/feedings
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "group_name": "Dairy herd",
  "date": "2026-10-31",
  "feed_type": "Alfalfa hay",
  "quantity_kg": 120
}
```
**Response `201`**
```json
{
  "id": "203a0119ccc44cc6bdcddb50c494eb9d",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "animal_id": null,
  "group_name": "Dairy herd",
  "date": "2026-10-31",
  "feed_type": "Alfalfa hay",
  "quantity_kg": 120.0,
  "notes": null
}
```


## 11. Finance
Managers and the owner only; workers and viewers get `403 forbidden_role`, so the apps hide Finance for them.
Income and expenses are records (`POST /v1/transactions`); selling an animal adds income automatically.
```http
POST /v1/transactions
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "type": "expense",
  "category": "feed",
  "amount": 850,
  "date": "2026-10-29"
}
```
**Response `201`**
```json
{
  "id": "3102b8a4d74c4313a3d010dd6d8dde7a",
  "created_at": "2026-10-31T20:37:32+00:00",
  "updated_at": "2026-10-31T20:37:32+00:00",
  "type": "expense",
  "category": "feed",
  "amount": 850.0,
  "date": "2026-10-29",
  "description": null,
  "animal_id": null
}
```

```http
GET /v1/finance/summary
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "date_from": "2026-10-02",
  "date_to": "2026-10-31",
  "currency": "TND",
  "income": 2400.0,
  "expenses": 850.0,
  "net": 1550.0,
  "income_by_category": {
    "animal_sale": 2400.0
  },
  "expenses_by_category": {
    "feed": 850.0
  },
  "monthly": [
    {
      "month": "2026-10",
      "income": 2400.0,
      "expenses": 850.0
    }
  ]
}
```


## 12. Dashboard (first tab)
The `finance` section is `null` for workers and viewers (finance is for managers and the owner).
One call returns everything the tiles need: animal counts, movements (births, deaths, sales, purchases), upcoming vaccinations, pregnancies, finance and production for the period.
```http
GET /v1/dashboard
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "generated_at": "2026-10-31T20:37:32+00:00",
  "period_days": 30,
  "period_from": "2026-10-02",
  "period_to": "2026-10-31",
  "animals": {
    "total": 2,
    "total_all_time": 3,
    "by_species": {
      "cattle": 2
    },
    "by_sex": {
      "female": 2
    },
    "by_status": {
      "active": 2,
      "sold": 1
    }
  },
  "movements": {
    "births": 1,
    "deaths": 0,
    "sales": 1,
    "purchases": 1
  },
  "health": {
    "upcoming_vaccinations": [
      {
        "reminder_id": "vacc_d51a155c6578438bae9390a0cf989cca",
        "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
        "animal_label": "Bella (CR-0412)",
        "title": "Vaccination due: Foot-and-mouth booster (Bella (CR-0412))",
        "due_date": "2026-11-01",
        "days_until": 1
      }
    ],
    "upcoming_vaccinations_count": 1,
    "overdue_vaccinations_count": 0,
    "sick_animals": 0,
    "ongoing_illnesses": 1
  },
  "breeding": {
    "pregnant_count": 0,
    "due_soon": []
  },
  "finance": {
    "currency": "TND",
    "income": 2400.0,
    "expenses": 850.0,
    "net": 1550.0
  },
  "unread_notifications": 0
}
```


## 13. Notifications
The bell on the Dashboard and More > Notifications. The daily job stores one notification per reminder bucket and pushes it through Firebase Cloud Messaging. Registering a phone:
```http
POST /v1/devices
Authorization: Bearer <Firebase ID token>
Content-Type: application/json

{
  "token": "fcm-token-example-0123456789",
  "platform": "android"
}
```
**Response `204`**
```json
(empty)
```

```http
GET /v1/notifications
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
[
  {
    "id": "49ca4ed47d2c44eca57f656a279f6e1d",
    "created_at": "2026-10-31T20:37:32+00:00",
    "updated_at": "2026-10-31T20:37:32+00:00",
    "title": "Farmivo reminder",
    "body": "Bella (CR-0412): Vaccination due: Foot-and-mouth booster (Bella (CR-0412)) is due tomorrow",
    "type": "vaccination",
    "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "reminder_id": "vacc_d51a155c6578438bae9390a0cf989cca",
    "read": false
  },
  {
    "id": "938520b5e64441dbb13284b4378095c7",
    "created_at": "2026-10-31T20:37:32+00:00",
    "updated_at": "2026-10-31T20:37:32+00:00",
    "title": "Farmivo reminder",
    "body": "Bella (CR-0412): Vet follow-up: Lameness check (Bella (CR-0412)) is due in 7 days",
    "type": "vet_visit",
    "animal_id": "e6a7e8ef6f8e4d7dbe3fa7cb139c9f8a",
    "reminder_id": "vet_b5f283d1de2843eba3141f95304be917",
    "read": false
  }
]
```

Mark one read: `POST /v1/notifications/{id}/read`; mark all: `POST /v1/notifications/read-all`; delete: `DELETE /v1/notifications/{id}`.

## 14. Reports (More > Reports)
`GET /v1/reports/<kind>` with kind `herd`, `vaccinations`, `financial` or `production`; optional `date_from` and `date_to` (default: the last 90 days). Without `format` the answer is JSON (shown below); the app adds `?format=csv` to download a CSV file it saves and opens.
```http
GET /v1/reports/herd
Authorization: Bearer <Firebase ID token>
```
**Response `200`**
```json
{
  "kind": "herd",
  "date_from": "2026-08-03",
  "date_to": "2026-10-31",
  "columns": [
    "ear_tag",
    "name",
    "species",
    "... (7 more)"
  ],
  "rows": [
    {
      "ear_tag": "CR-0301",
      "name": "Thor",
      "species": "cattle",
      "breed": null,
      "sex": "male",
      "date_of_birth": "2019-12-27",
      "age_label": "6y 10m",
      "date_added": "2026-10-31",
      "status": "sold",
      "status_date": "2026-10-31"
    },
    {
      "ear_tag": "CR-0412",
      "name": "Bella",
      "species": "cattle",
      "breed": "Holstein-Friesian",
      "sex": "female",
      "date_of_birth": "2022-03-06",
      "age_label": "4y 7m",
      "date_added": "2023-07-19",
      "status": "active",
      "status_date": null
    },
    {
      "ear_tag": "CR-0501",
      "name": null,
      "species": "cattle",
      "breed": "Holstein-Friesian",
      "sex": "female",
      "date_of_birth": "2026-10-31",
      "age_label": "0d",
      "date_added": "2026-10-31",
      "status": "active",
      "status_date": null
    }
  ]
}
```


## 15. Errors you can see

Every error has the shape `{"detail": ...}`. Membership and role errors (`403`) add a `code`: `no_farm`, `pending`, `rejected`, `forbidden_role`.
```http
GET /v1/animals
```
**Response `401`**
```json
{
  "detail": "Missing bearer token"
}
```

```http
GET /v1/nope
Authorization: Bearer <Firebase ID token>
```
**Response `404`**
```json
{
  "detail": "Not Found"
}
```


A worker opening finance:
```http
GET /v1/finance/summary
Authorization: Bearer <Firebase ID token>
```
**Response `403`**
```json
{
  "detail": "Your role (worker) does not allow this",
  "code": "forbidden_role"
}
```

| Status | Meaning | What the user sees |
|---|---|---|
| 401 | Missing, invalid or expired Firebase token | The app refreshes the token once, then asks to sign in again |
| 403 `no_farm` / `pending` / `rejected` | No farm yet, waiting for approval, request refused | Create-or-join screen, waiting screen, or the refusal message |
| 403 `forbidden_role` | The user's role may not do this (e.g. a worker opening finance) | The server's message; the app normally hides these actions |
| 404 | The record, or the URL, does not exist | "Not Found" plus the URL (Android) |
| 409 | Duplicate ear tag, birth already recorded, already in a farm, owner leaving | The server's message |
| 422 | Data failed validation | The first validation message |
| 503 | The server cannot reach MongoDB | "Database unavailable" |

## 16. "Everything is 404 / nothing loads": check list

1. `curl http://YOUR_SERVER:8000/healthz` must print `{"status":"ok"}`.
```http
GET /v1/healthz
```
**Response `200`**
```json
{
  "status": "ok"
}
```

2. `curl -i http://YOUR_SERVER:8000/v1/farm` must answer **401** (the API is there and wants a token). A 404 here means a different program answers on that port, or a proxy strips `/v1`.
3. The app's base URL must end in `/v1/` and point at the server (Android: `farmivoApiUrl` in `gradle.properties`, iOS: `API_BASE_URL` in `Config/*.xcconfig`). The apps add `/v1/` if it is missing.
4. Real phones cannot use `10.0.2.2` or `localhost`; use the server's address.
5. Calling the API by hand: get a token with Firebase REST (`POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<Web API key>` with `{"email","password","returnSecureToken":true}`), then `curl -H "Authorization: Bearer <idToken>" http://YOUR_SERVER:8000/v1/farm`.
6. On the server: `supervisorctl status farmivo` and `tail -n 50 /var/log/farmivo/*.log` show the real error (for example a MongoDB login problem).
