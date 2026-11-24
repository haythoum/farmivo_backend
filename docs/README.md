# Farmivo documentation

**Smart Farming. Better Living.** Livestock management for small and mid-size farms: Android (Java), iOS (Swift), Python backend.

Start here. The three repositories each have a `docs/` folder; this one (backend) holds the system-wide documents.

| Document | What it answers |
|---|---|
| [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md) | **Start here.** How backend, Android and iOS connect: components, deployment, sequence diagrams, screen → endpoint → code → collection map, configuration matrix, errors, security, glossary |
| [ROLES_AND_MEMBERS.md](ROLES_AND_MEMBERS.md) | Farm members: owner, manager, worker, viewer; invite codes and approval; who may call what; what the apps show for each status |
| [CODE_REFERENCE.md](CODE_REFERENCE.md) | Every backend module, class, function and route: what it does, parameters, errors, side effects |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the whole system fits together: module map, request flow, auth, reminders, photos, languages, money (costs, balance sheet, sales), breeding rules, breed photos, app design |
| [DATA_MODEL.md](DATA_MODEL.md) | What is stored in MongoDB, collections, relations, business rules |
| [API.md](API.md) | The REST contract the apps use (every endpoint, field, error) |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Set up Firebase + MongoDB, run the backend, build both apps, deploy, test |
| [DECISIONS.md](DECISIONS.md) | Why things were built this way (MongoDB, generic records, no per-entity models, ...) |
| [BRANDING.md](BRANDING.md) | Logo files, colour palette, where "Powered by Quadralens" appears |
| [APP_FLOWS.md](APP_FLOWS.md) | Screen-by-screen guide: what each action calls and what comes back (real example responses), plus the "everything is 404" checklist |
| [STATUS.md](STATUS.md) | What is done, release notes with their deploy steps, what was **not** verified, known gaps, suggested next steps |
| [ADMIN.md](ADMIN.md) | The admin web dashboard **<http://51.83.71.157:8000/admin>**: activity, app versions, problems, farms and users (support), breed photos, announcements; how to turn it on |
| [REVIEW_2026-11-03.md](REVIEW_2026-11-03.md) | Backend review of 3 November 2026: every finding, fixed or not, with severity |

Per app: [Android docs](https://github.com/haythoum/farmivo_android/tree/feature/initial-app/docs) · [iOS docs](https://github.com/haythoum/farmivo_ios/tree/feature/initial-app/docs)

The UI mockup (7 screens) is the "Farmivo App Mockup" artifact in Claude; its screens map to the features below.

## Feature map

| Feature | Backend | Android screen | iOS screen |
|---|---|---|---|
| 1. Animal profiles (farm number, ear tag, name, species, breed with photo, sex, colour, DOB or age by teeth, barn, photo, status, costs) | `routers/animals.py`, `animal_codes.py`, `breeds.py`, `breed_photos.py`, `costs.py` | `AnimalsFragment`, `AnimalProfileFragment`, `AnimalFormActivity`, `BreedPhotos` | `AnimalsView`, `AnimalDetailView`, `BreedPickSheet` |
| Barns (species, capacity) | `routers/barns.py` | `BarnsFragment`, Home barn cards | `BarnsView`, `HomeView` |
| 2. Health & vaccination (history, next dates, treatments, vet visits, illness/recovery, auto reminders) | `routers/health.py`, `services/reminders.py` | Health tab (`ResourceTabsFragment`) | `HealthView` |
| 3. Breeding (mating rules, pregnancy, miscarriage, expected birth, births/offspring, family) | `routers/breeding.py`, `breeding_rules.py`, `GET /animals/{id}/family` | Breeding tab, `BirthDialog` | `BreedingView`, `BirthSheet` |
| 4. Growth & production (weights, milk/eggs, feeding, charts) | `routers/growth.py` | Growth screen, `GrowthChartView` | `GrowthView` (Swift Charts) |
| 5. Home (barns, counts, alerts, finance tile, reports, notifications) | `routers/dashboard.py`, `reports.py`, `notifications.py` | `DashboardFragment`, Reports/Notifications | `HomeView`, `ReportsView`, `NotificationsView` |
| Finance (expenses shared by animals, balance sheet per barn, sales with each animal's result) | `routers/finance.py`, `costs.py`, `sales.py` | `FinanceFragment` | `FinanceView`, `SaleDetailSheet` |
| 6. Farm members (create or join a farm, approval, roles) | `routers/members.py`, `services/membership.py`, `permissions.py` | `FarmSetupActivity`, `WaitingActivity`, `MembersFragment` | `FarmSetupView`, `WaitingView`, `MembersView` |
| Offline: lists kept on the phone, changes sent when the internet is back | (normal API) | `data/Offline` | `Core/Networking/OfflineStore` |
| For sale (Eid, market): price, note, share to WhatsApp | `for_sale`, `asking_price`, `sale_note`, `?for_sale=true`, `latest_weight_kg` in `routers/animals.py` | `ui/ForSale`, `AnimalsFragment` (chip) | `ForSale` (`WorkKit.swift`), `AnimalsView` |
| Several animals at once: move, vaccinate, weigh, sell; a whole barn | `POST /vaccinations/bulk` (`health.py`), `POST /weights/bulk` (`growth.py`), `POST /animals/move` | `ui/BulkWork`, `AnimalsFragment` selection | `BulkWork`, `WeighingSheet`, `MoveManySheet` (`WorkKit.swift`) |
| Feed stock (sacks in / out, feed expense, low stock warning) | `routers/feed_stock.py` | `ui/FeedStockFragment` | `Feeding/Views/FeedStockView` |
| Monthly finance summary (PDF) | `GET /finance/month-report` (`month_report.py`) | `ui/MonthReport` (print to PDF) | `MonthReportSheet`, `PDFMaker` |
| Announcements from Farmivo | `routers/support.py`, admin › Announcements | `ui/Announcements` | `Announcements` (`WorkKit.swift`) |
| Admin dashboard, problems log, app versions | `app/admin/`, `app/ops.py` | sends `X-Farmivo-*` headers (`ApiClient.appHeaders`) | sends `X-Farmivo-*` headers (`APIClient.appHeaders`) |

## Builds

No automatic builds: the GitHub Actions workflows were removed on 24 Nov 2026 because they cost money (storage and macOS minutes). Build and test in Android Studio and Xcode before each release. The branch `ci-status` keeps the last old reports.
