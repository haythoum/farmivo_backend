# Farm members and roles

Several people can work on the same farm. One person creates the farm and becomes its **owner**; everyone else **asks to join** with the farm's **invite code**, and the owner or a manager **approves** them with a role. The server enforces the roles on every request.

Code: `app/services/membership.py` (rules), `app/routers/members.py` (endpoints), `app/permissions.py` (who may call what), `app/deps.py` (`get_identity`, `get_ctx`). Endpoints and shapes: [API.md, Members & roles](API.md#members--roles).

## Concepts

| Term | Meaning |
|---|---|
| **Owner** | Created the farm (or received it by transfer). Exactly one per farm. Can do everything, including transferring ownership. Cannot leave or be removed while owner. |
| **Manager** | Everything except transferring ownership and changing or removing the owner: finance, deleting records, farm settings, approving and managing members, rotating the invite code. |
| **Worker** | Daily work: reads everything except finance; creates and edits animals, health, breeding, growth, production, feeding, reminders. Cannot delete records (except notifications), see finance, change farm settings or manage members. |
| **Viewer** | Read-only (for a vet or an advisor): reads everything except finance; can mark notifications read. |
| **Invite code** | Short code like `GVF-7K3P`: three letters from the farm name ("Green Valley Farm" gives `GVF`) and four random characters without look-alikes (no 0/O, 1/I/L). Managers and the owner see it in Farm settings and share it. Rotating it makes the old code stop working. A code alone gives no access: every request must be approved. |
| **Status** | Where a user stands, from `GET /me`: `none` (no farm), `pending` (asked to join, waiting), `active` (member with a role), `rejected` (request refused). |

A user belongs to **one farm at a time**. Asking to join another farm replaces a pending request; to switch farms an active member leaves first.

## Email verification code

Before creating or joining a farm, a new account confirms its email with a **6-digit code** that the server emails to it (`app/services/verification.py`, `app/services/mailer.py`).

1. After `createUserWithEmailAndPassword` the app calls `GET /me`: `email_verified: false`, so it shows "Enter the 6-digit code" and calls `POST /me/verification/send`.
2. The server creates a random code, keeps only its hash in `email_codes/<uid>` and emails it ("482715 is your Farmivo code"). The code expires after **15 minutes**. A new code can be asked for after **60 seconds** (`429 too_soon` with `retry_after` before that), at most **5 per hour** (`429 too_many_codes`).
3. The user types it: `POST /me/verification/verify {code}`. Right: `email_verified: true` (also set in Firebase), the app moves on to "Create or join a farm". Wrong: `400 wrong_code` with the attempts left; after **5** wrong tries the code is burnt (`429 too_many_attempts`) and a new one must be sent. Expired: `410 code_expired`.
4. `POST /farms` and `POST /farms/join` answer `403 email_unverified` until then.

Accounts that were already active farm members, and accounts whose Firebase email is already verified, count as verified without a code. Without email settings (`MAILJET_API_KEY` empty) the code is written to the server log instead of being sent, for testing.

```mermaid
sequenceDiagram
  actor U as New user
  participant App
  participant API as Farmivo API
  participant Mail as Mail server
  App->>API: GET /v1/me
  API-->>App: email_verified false, status none
  App->>API: POST /v1/me/verification/send
  API->>API: random 6 digits, store hash, expires in 15 min
  API->>Mail: email with the code
  API-->>App: sent_to, resend_after_seconds 60
  Mail-->>U: 482715 is your Farmivo code
  U->>App: types 482715
  App->>API: POST /v1/me/verification/verify {code}
  API-->>App: Me with email_verified true
  App->>App: Create or join a farm
```

## Permission matrix

| Action | viewer | worker | manager | owner |
|---|:-:|:-:|:-:|:-:|
| Read animals, health, breeding, growth, production, feeding, reminders, notifications, dashboard (without finance), herd / vaccination / production reports, farm | ✓ | ✓ | ✓ | ✓ |
| Mark notifications read, read all | ✓ | ✓ | ✓ | ✓ |
| Create and edit records (POST / PATCH), upload photos, change animal status, record births, mark reminders done | | ✓ | ✓ | ✓ |
| Delete notifications | | ✓ | ✓ | ✓ |
| Delete records (animals, health, breeding, growth, production, feeding, reminders) | | | ✓ | ✓ |
| Finance: transactions, totals, financial report, dashboard `finance` | | | ✓ | ✓ |
| Farm settings (`PATCH /farm`), see the invite code | | | ✓ | ✓ |
| Members: list, approve, reject, change role (manager, worker, viewer), remove; rotate invite code | | | ✓ | ✓ |
| Change or remove the owner | | | | (transfer) |
| Transfer ownership | | | | ✓ |

How it is enforced: every farm endpoint calls `get_ctx()`, which loads the caller's membership and compares their role with `required_role(method, path)` in `app/permissions.py`:

| Rule (first match wins) | Lowest role |
|---|---|
| `/farm/transfer-ownership` | owner |
| `/transactions`, `/finance`, `/reports/financial`, `/farm/members`, `/farm/invite-code` | manager |
| any `GET` | viewer |
| `POST /notifications/{id}/read`, `POST /notifications/read-all` | viewer |
| other `/notifications` writes (delete) | worker |
| `PATCH /farm` | manager |
| any other `DELETE` | manager |
| any other `POST` / `PATCH` | worker |

A new route is therefore protected without extra code. The dashboard is readable by everyone; its `finance` section is `null` below manager.

## Flows

### Create a farm

```mermaid
sequenceDiagram
  actor U as New user
  participant App
  participant FB as Firebase Auth
  participant API as Farmivo API
  participant DB as MongoDB
  U->>App: Create account (email, password)
  App->>FB: createUser
  FB-->>App: ID token
  App->>API: GET /v1/me
  API-->>App: status none
  U->>App: choose "Create a new farm", name and address
  App->>API: POST /v1/farms {name, address}
  API->>DB: farms (owner_uid, invite_code), members (owner, active), users (farm_id, active)
  API-->>App: 201 Me (status active, role owner)
  App->>App: open the dashboard
```

### Join a farm and get approved

```mermaid
sequenceDiagram
  actor W as New worker
  participant WApp as Worker app
  participant API as Farmivo API
  participant DB as MongoDB
  participant FCM as Firebase Cloud Messaging
  participant MApp as Owner or manager app
  W->>WApp: choose "Join a farm", type invite code
  WApp->>API: POST /v1/devices (push token, works without a farm)
  WApp->>API: POST /v1/farms/join {invite_code}
  API->>DB: members (status pending, role worker), users (status pending)
  API->>DB: notifications (type join_request)
  API->>FCM: push "Ali wants to join" to owner and managers
  API-->>WApp: 200 Me (status pending)
  WApp->>WApp: waiting screen, any farm call answers 403 code pending
  FCM-->>MApp: notification
  MApp->>API: GET /v1/farm/members
  API-->>MApp: pending requests first
  MApp->>API: POST /v1/farm/members/uid/approve {role worker}
  API->>DB: members (status active, role), users (status active)
  API->>FCM: push "Welcome to Green Valley Farm" to the worker
  FCM-->>WApp: notification
  WApp->>API: GET /v1/me
  API-->>WApp: status active, role worker
  WApp->>WApp: open the dashboard, hide what a worker cannot do
```

### Reject, leave, remove, transfer

- **Reject**: `POST /farm/members/{uid}/reject` gives `status: "rejected"` and a push. The person may ask again or create their own farm.
- **Leave / cancel**: `DELETE /me/membership`. The owner gets `409 "Transfer ownership first"`.
- **Remove**: `DELETE /farm/members/{uid}` (manager or owner, never the owner). The person's next request answers `403 no_farm`.
- **Transfer**: `POST /farm/transfer-ownership {uid}` (owner only, target must be active). The previous owner becomes a manager, `farms.owner_uid` changes.
- **Role change**: `PATCH /farm/members/{uid} {role}` takes effect on that person's next request (roles are read on every request).

## Errors

All `403` membership and role errors carry a `code`:

| Status, `code` | Meaning | App behaviour |
|---|---|---|
| `403 no_farm` | No farm (new, removed or left) | Show "Create a farm" / "Join a farm" |
| `403 pending` | Waiting for approval; `detail` names the farm | Waiting screen, "Cancel request", re-check `GET /me` on resume and on the approval push |
| `403 rejected` | Request refused | Explain, then "Create a farm" / "Join another farm" |
| `403 forbidden_role` | The role may not do this | Show `detail`; the UI should normally hide the action |
| `404 "No farm with this code"` | Wrong invite code | Inline error under the code field |
| `409` | Conflicts: already in a farm, owner leaving, changing the owner, approving a non-pending request | Show `detail` |

## What the apps do with `GET /me`

First `email_verified`: while it is false the app shows the email-code screen, whatever the status. Then:

Call it after sign-in, on app start, when the app returns to the foreground, and when a `membership_approved` / `membership_rejected` push arrives.

| `status` | Screen |
|---|---|
| `none` | Choose: **Create a new farm** (name, address) or **Join a farm** (invite code) |
| `pending` | "Waiting for approval from {farm.name}" with **Cancel request** and **Sign out** |
| `rejected` | "Your request to join {farm.name} was not accepted" with **Create a farm** / **Join another farm** |
| `active` | The app; show or hide actions by `role` using the matrix above. More > **Members** for managers and the owner, invite code in Farm settings |

## State machine (the member record is the source of truth)

`GET /v1/me` reads the member record. `users/<uid>` is only a pointer (`farm_id`, `status`) used to find it quickly; when they disagree the member record wins and the pointer is repaired on the spot. If the pointer is missing or points to the wrong farm, the member record is looked up across all farms (active first, then pending, then the latest rejection). **Signing out changes nothing on the server** except removing the phone's push token (`DELETE /v1/devices`).

| From | Action | Member record | `users/<uid>` | `GET /me` status |
|---|---|---|---|---|
| none | `POST /farms` | created: owner, active | farm, active | active (owner) |
| none / rejected | `POST /farms/join` | created: worker, pending (a pending request elsewhere is deleted) | farm, pending | pending |
| pending | approve (manager/owner) | active, chosen role | farm, active | active |
| pending | reject (manager/owner) | rejected | farm, rejected | rejected |
| pending | `DELETE /me/membership` | deleted | cleared | none |
| active (not owner) | `DELETE /me/membership` | deleted | cleared | none |
| active (not owner) | removed by manager/owner | deleted | cleared | none |
| active owner | transfer ownership | old owner -> manager, new owner -> owner | unchanged | active (new roles) |
| any | `DELETE /me` (delete account) | all of the user's member records deleted (owner alone: whole farm) | deleted | none (account gone) |
| legacy account (users.farm_id = a farm it owns, no member record) | any request | created: owner, active | farm, active | active (owner) |
| any | sign out / sign in | unchanged | unchanged (repaired if stale) | unchanged |

Join-request notifications are marked read when the request is decided (approve, reject, cancel, remove).

## Data

See [DATA_MODEL.md](DATA_MODEL.md#members-and-users).

- `members` (`farms/<farm_id>/members/<uid>`): `_id` = Firebase uid, `farm_id`, `uid`, `email`, `name`, `role`, `status` (`pending`, `active`, `rejected`), `requested_at`, `decided_at`, `decided_by`.
- `users` (`users/<uid>`): `_id` = uid, `farm_id`, `status` (a pointer to the member record, repaired automatically), plus `email_verified`, `lang`.
- `farms`: `owner_uid`, `invite_code` (uppercase, unique).

Accounts created before memberships existed (a `users` document and a farm whose `owner_uid` is the user, no member record) become **active owners** on their first request, and their farm gets an invite code the first time a manager or owner opens it. Nothing has to be run on the server.
