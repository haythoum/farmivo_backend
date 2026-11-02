# Branding

Farmivo is an app for livestock keepers, so the identity is built around the animals: a **cattle-head logo** on a warm, earthy palette. The apps carry the line **"Powered by Quadralens"** on the sign-in screen and in the More/Settings tab.

## Logo

Original drawing (not derived from any existing mark). Cream face, sunflower horns and muzzle, teal eyes and nostrils, on a teal tile.

| File | Use |
|---|---|
| `docs/brand/farmivo-logo.svg` / `.png` | Full logo (tile + head), 512 px PNG |
| `docs/brand/farmivo-mark.svg` | Head only, transparent background |
| `docs/brand/farmivo-icon-square.svg` | Square app-icon source (1024 px PNG is in the iOS asset catalog) |
| `docs/brand/farmivo-mark-1024.png` | Head only, 1024 px, transparent background (print, presentations) |
| `docs/brand/farmivo-wordmark-light.png` / `-dark.png` | Logo tile + "Farmivo" + tagline, 1600 × 480, on cream or on teal |

Where it lives in the apps:
- Android: `res/drawable/ic_logo.xml` (login), `ic_launcher_foreground.xml` + `ic_launcher_background` colour (adaptive icon).
- iOS: `Assets.xcassets/Logo.imageset`, `Assets.xcassets/AppIcon.appiconset` (1024 px).

## Palette

| Role | Light | Dark | Name |
|---|---|---|---|
| Primary | `#1F6F6B` | `#7CCBC5` | Pasture teal |
| Primary dark / tile | `#134A47` | | Deep teal |
| Accent | `#F2B544` | `#F2C766` | Sunflower |
| Background | `#FBF6EE` | | Cream |
| Surface tint | `#DDEEEC` | | Mist |
| Text | `#1E2A29` | | Ink |
| Muted text | `#5B6B69` | | |
| Alert | `#B3261E` | | |

Android: `res/values/colors.xml` and `values-night/colors.xml`. iOS: colour sets `BrandPrimary`, `AccentColor`, `BrandAccent`, `OnBrandPrimary`.

## "Powered by Quadralens"

- Android: string `powered_by`; shown in `activity_login.xml` and at the bottom of `MoreFragment`.
- iOS: `PoweredByView` (in `Cards.swift`); shown in `LoginView` and `MoreView`.
- Mockup: bottom of the sign-in screen.

Change the wording in one place per platform (string resource / `PoweredByView`).

## Rules of thumb
- Keep the head on the teal tile or on cream; don't recolour the horns.
- Minimum size 24 px for the mark.
- Tagline: "Smart Farming. Better Living."

## Store assets
Store icons, feature graphic, screenshots (en / fr / ar) and listing texts live in each app repo under `fastlane/`; the checklists are `docs/STORE_RELEASE.md` in farmivo_android and farmivo_ios.
