# Farmivo documentation

**Smart Farming. Better Living.** Livestock management for small and mid-size farms: Android (Java), iOS (Swift), Python backend.

Start here. The three repositories each have a `docs/` folder; this one (backend) holds the system-wide documents.

| Document | What it answers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the whole system fits together: components, request flow, auth, reminders, photos |
| [DATA_MODEL.md](DATA_MODEL.md) | What is stored in MongoDB, collections, relations, business rules |
| [API.md](API.md) | The REST contract the apps use (every endpoint, field, error) |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Set up Firebase + MongoDB, run the backend, build both apps, deploy, test |
| [DECISIONS.md](DECISIONS.md) | Why things were built this way (MongoDB, generic records, no per-entity models, ...) |
| [BRANDING.md](BRANDING.md) | Logo files, colour palette, where "Powered by Quadralens" appears |
| [APP_FLOWS.md](APP_FLOWS.md) | Screen-by-screen guide: what each action calls and what comes back (real example responses), plus the "everything is 404" checklist |
| [STATUS.md](STATUS.md) | What is done, what was **not** verified, known gaps, suggested next steps |

Per app: [Android docs](https://github.com/haythoum/farmivo_android/tree/feature/initial-app/docs) · [iOS docs](https://github.com/haythoum/farmivo_ios/tree/feature/initial-app/docs)

The UI mockup (7 screens) is the "Farmivo App Mockup" artifact in Claude; its screens map to the features below.

## Feature map

| Feature | Backend | Android screen | iOS screen |
|---|---|---|---|
| 1. Animal profiles (ear tag, name, species, breed, sex, DOB/age, date added, photo, status) | `routers/animals.py` | `AnimalsFragment`, `AnimalProfileFragment`, `AnimalFormActivity` | `AnimalsView`, `AnimalDetailView` |
| 2. Health & vaccination (history, next dates, treatments, vet visits, illness/recovery, auto reminders) | `routers/health.py`, `services/reminders.py` | Health tab (`ResourceTabsFragment`) | `HealthView` |
| 3. Breeding (mating, pregnancy, expected birth, births/offspring, family) | `routers/breeding.py`, `GET /animals/{id}/family` | Breeding tab, `BirthDialog` | `BreedingView`, `BirthSheet` |
| 4. Growth & production (weights, milk/eggs, feeding, charts) | `routers/growth.py` | Growth screen, `GrowthChartView` | `GrowthView` (Swift Charts) |
| 5. Dashboard (counts, births/deaths/sales, upcoming vaccinations, finance, reports, notifications) | `routers/dashboard.py`, `finance.py`, `reports.py`, `notifications.py` | `DashboardFragment`, Finance/Reports/Notifications | `DashboardView`, `FinanceView`, `ReportsView`, `NotificationsView` |
