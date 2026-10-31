# Branding

Farmivo is an app for livestock keepers, so the identity is built around the animals: a **cattle-head logo** on a warm, earthy palette. The apps carry the line **"Powered by Quadralens"** on the sign-in screen and in the More/Settings tab.

## Logo

Original drawing (not derived from any existing mark). Cream face, wheat horns and muzzle, rust eyes and nostrils, on a rust tile.

| File | Use |
|---|---|
| `docs/brand/farmivo-logo.svg` / `.png` | Full logo (tile + head), 512 px PNG |
| `docs/brand/farmivo-mark.svg` | Head only, transparent background |
| `docs/brand/farmivo-icon-square.svg` | Square app-icon source (1024 px PNG is in the iOS asset catalog) |

Where it lives in the apps:
- Android: `res/drawable/ic_logo.xml` (login), `ic_launcher_foreground.xml` + `ic_launcher_background` colour (adaptive icon).
- iOS: `Assets.xcassets/Logo.imageset`, `Assets.xcassets/AppIcon.appiconset` (1024 px).

## Palette

| Role | Light | Dark | Name |
|---|---|---|---|
| Primary | `#8C4A2F` | `#E0A07F` | Barn rust |
| Primary dark / tile | `#5E2F1D` | | Deep rust |
| Accent | `#E9B44C` | `#F2C766` | Wheat |
| Background | `#FBF6EE` | | Cream |
| Surface tint | `#F5E6DC` | | Clay |
| Text | `#2A1F1A` | | Soil |
| Muted text | `#6B5A50` | | |
| Alert | `#B3261E` | | |

Android: `res/values/colors.xml` and `values-night/colors.xml`. iOS: colour sets `BrandPrimary`, `AccentColor`, `BrandAccent`, `OnBrandPrimary`.

## "Powered by Quadralens"

- Android: string `powered_by`; shown in `activity_login.xml` and at the bottom of `MoreFragment`.
- iOS: `PoweredByView` (in `Cards.swift`); shown in `LoginView` and `MoreView`.
- Mockup: bottom of the sign-in screen.

Change the wording in one place per platform (string resource / `PoweredByView`).

## Rules of thumb
- Keep the head on the rust tile or on cream; don't recolour the horns.
- Minimum size 24 px for the mark.
- Tagline: "Smart Farming. Better Living."
