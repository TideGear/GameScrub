# BannerHub Store Features — Planning Report & Progress Log

**Created:** 2026-04-14  
**Purpose:** Track all planned store feature additions across GOG, Epic, and Amazon. When complete, confirmed working features will be ported to BannerHub Lite.

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🔵 | Next up / in progress |
| ✅ | Complete + CI passing |
| ❌ | Attempted — not working / abandoned |
| ⚠️ | Partial — works with caveats |
| 🔄 | Complete — needs BH-Lite port |

---

## Session Resume (update this block every session)

**Current stable:** v3.0.0 (commit `19c6092d8`)
**Active pre:** v3.0.4-pre (commit `bf80e9c8b`) — CI pending

**Last completed:** GOG-1 Cloud Saves + EPIC-2 Cloud Saves (v3.0.4-pre)
**Next job:** GOG-4 GOG Connect (low priority) or BH-Lite ports

---

## Master Job List

### Detail Page Foundation (all stores)
| # | Job | Status | Notes |
|---|-----|--------|-------|
| D-1 | Full-screen detail activities (GOG/Epic/Amazon) | ✅ v3.0.1-pre | Header, cover art, GAME INFO, ACTIONS, stubs |
| D-2 | Strip HTML from descriptions | ✅ v3.0.1-pre | `Html.fromHtml()` in GOG + Epic detail |
| D-3 | Install size in GAME INFO | ✅ v3.0.1-pre | GOG: sync-time; Epic/Amazon: lazy+cached |
| D-5 | Release date in GAME INFO | ✅ v3.0.1-pre | GOG+Epic synced to SP; Amazon skipped (no API source) |
| D-6 | Ratings / score in GAME INFO | ✅ v3.0.2-pre | GOG only (0–5★ from rating field); Epic/Amazon no reliable source |

### GOG
| # | Job | Status | Notes |
|---|-----|--------|-------|
| GOG-1 | Cloud Saves | ✅ v3.0.4-pre | Manual save folder; FolderPickerActivity; cloudstorage.gog.com |
| GOG-2 | Update Checker | ✅ v3.0.1-pre | `content-system.gog.com/products/{id}/os/windows/builds`; compare `gog_build_{id}` |
| GOG-3 | DLC Management | ✅ v3.0.3-pre | DLCs detected during sync; shown in detail with "Owned" badge; gen2 installs include depots |
| GOG-4 | GOG Connect | ❌ | Discontinued by GOG — removed |

### Epic Games
| # | Job | Status | Notes |
|---|-----|--------|-------|
| EPIC-1 | Free Games (dedicated screen) | ✅ v3.0.2-pre | Full-screen EpicFreeGamesActivity; FREE button in header; tappable store links |
| EPIC-2 | Cloud Saves | ✅ v3.0.4-pre | Manual save folder; FolderPickerActivity; datastorage Epic API |
| EPIC-3 | Update Checker | ✅ v3.0.1-pre | manifest buildVersion field; confirmed working |
| EPIC-4 | DLC / Add-on Management | ✅ v3.0.3-pre | DLCs detected via mainGameItem; shown in detail with Install button + inline progress |

### Amazon Games
| # | Job | Status | Notes |
|---|-----|--------|-------|
| AMAZON-1 | Update Checker | ✅ v3.0.1-pre | getGameDownload versionId; confirmed working |
| AMAZON-2 | DLC Management | ⚠️ v3.0.3-pre | Best-effort productType detection; shown in detail with Install button; field names uncertain |

---

## Cloud Saves — User Flow

### Overview
Cloud saves let users back up and restore game save files between their device and the store's cloud storage. Because save file locations vary per game and Wine containers are in the app's private files directory (not easily accessible via Android file pickers), the save folder must be set manually by the user.

---

### GOG Cloud Saves — User Flow

**First-time setup:**
1. Open the GOG game detail screen for an installed game
2. Scroll to the **CLOUD SAVES** section
3. The section shows: *"No save folder set"* with a **Browse** button
4. Tap **Browse** → opens the in-app folder picker, starting at the app's private files directory (where Wine containers live)
5. Navigate into your Wine container → `drive_c` → save file location (e.g. `users/user/Documents/My Games/GameName/`)
6. Tap **"Select this folder"** when the correct folder is shown
7. The path is saved to the game's prefs entry (`gog_save_dir_{gameId}`)

**Uploading saves to cloud:**
1. With save folder set, tap **Upload Saves**
2. App scans the local folder for all files
3. Fetches the cloud save file list from GOG (`cloudstorage.gog.com/v1/{userId}/{gameId}`)
4. Compares `last_modified` timestamps — uploads files that are newer locally than in the cloud
5. Status line updates: *"Uploaded N files"* or *"Already up to date"*

**Downloading saves from cloud:**
1. Tap **Download Saves**
2. App fetches the cloud save file list
3. Downloads each file to the local save folder, overwriting local files
4. Status line updates: *"Downloaded N files"* or *"No cloud saves found"*

**Notes:**
- The save folder path persists across sessions — only needs to be set once per game
- The GOG `clientId` used is the game's product ID (correct for most GOG games)
- Upload/download happens on a background thread; status updates live in the UI
- No conflict resolution in this version — download always overwrites local; upload only sends newer files

---

### Epic Cloud Saves — User Flow

**First-time setup:**
1. Open the Epic game detail screen for an installed game
2. Scroll to the **CLOUD SAVES** section
3. The section shows: *"No save folder set"* with a **Browse** button
4. Tap **Browse** → opens the in-app folder picker, starting at the app's private files directory
5. Navigate into your Wine container → `drive_c` → save file location
6. Tap **"Select this folder"** when the correct folder is shown
7. The path is saved to the game's prefs entry (`epic_save_dir_{appName}`)

**Uploading saves to cloud:**
1. With save folder set, tap **Upload Saves**
2. App scans the local folder for all files
3. Fetches the Epic cloud save file list (`datastorage-public-service-liveegs.live.use1a.on.epicgames.com/api/v1/access/egstore/savesync/{accountId}/{appName}/`)
4. For each local file that is newer than the cloud version (or missing from cloud): POST to get a `writeLink`, then PUT the file bytes to that URL
5. Status line updates: *"Uploaded N files"* or *"Already up to date"*

**Downloading saves from cloud:**
1. Tap **Download Saves**
2. App fetches the cloud save file list
3. Downloads each file via its `readLink` URL to the local save folder
4. Status line updates: *"Downloaded N files"* or *"No cloud saves found"*

**Notes:**
- Same folder-per-game persistence as GOG
- Epic cloud saves require a valid OAuth token (auto-refreshed)
- Each file's write URL must be requested individually via POST before uploading
- No conflict resolution in this version — download always overwrites local; upload only sends newer files

---

### In-App Folder Picker (FolderPickerActivity)

Used by both GOG and Epic cloud saves setup.

- Opens at `getFilesDir()` — the app's private files directory, which contains all Wine containers
- Shows a list of subdirectories (files hidden)
- Navigation: tap a directory to enter it; **"↑ Up"** button to go to parent
- Current path shown in header (truncated to last 2 segments if long)
- **"Select this folder"** button always visible — selects the currently displayed directory
- Returns selected path via `setResult(RESULT_OK, intent.putExtra("path", selectedPath))`
- Opened via `startActivityForResult()` from the detail activity; result received in `onActivityResult()`

---

## Completed Features Detail

### D-1: Full-screen Detail Activities (v3.0.1-pre)
Replaced inline expand cards with full-screen `GogGameDetailActivity`, `EpicGameDetailActivity`, `AmazonGameDetailActivity`. Each has: header bar (← back + title), cover art strip, scrollable body with GAME INFO, ACTIONS, UPDATES, DLC, CLOUD SAVES sections.

### D-2: HTML Description Strip (v3.0.1-pre)
GOG and Epic descriptions contain HTML tags from the API. Applied `Html.fromHtml()` before displaying in detail views.

### D-3: Install Size in GAME INFO (v3.0.1-pre)
GOG: fetched and cached at sync time. Epic/Amazon: fetched lazily on detail open, cached in prefs.

### D-5: Release Date in GAME INFO (v3.0.1-pre)
GOG: from `release_date` field in product API, cached as `gog_release_{gameId}`. Epic: from `viewableDate` / `effectiveDate` in catalog API, cached as `epic_release_{appName}`. Amazon: no reliable source.

### D-6: Ratings in GAME INFO (v3.0.2-pre)
GOG only. `rating` field (0–500 integer) shown as 0.0–5.0★ in GAME INFO card. Only populated after a library ↺ refresh (written during `fetchGame()` in sync).

### GOG-2: Update Checker (v3.0.1-pre)
Fetches `content-system.gog.com/products/{id}/os/windows/builds?generation=2`, compares `items[0].build_id` against stored `gog_build_{gameId}`. Shows "Up to date" or "Update available" + Update button.

### EPIC-3: Update Checker (v3.0.1-pre)
Re-fetches manifest API, reads `buildVersion` from `elements[0]`. Compares against stored `epic_manifest_version_{appName}`. Shows update status + button.

### AMAZON-1: Update Checker (v3.0.1-pre)
Calls `getGameDownload(entitlementId).versionId`, compares against stored `amazon_manifest_version_{productId}`.

### EPIC-1: Free Games (v3.0.2-pre)
Dedicated `EpicFreeGamesActivity`. Green "FREE" button in Epic library header. Fetches `freeGamesPromotions` endpoint (no auth). Shows "FREE THIS WEEK" and "FREE COMING SOON" sections. Each card tappable — opens Epic Store page in system browser via `ACTION_VIEW`.

### GOG-3: DLC Management (v3.0.3-pre)
During sync, DLCs (detected via `game_type == "dlc"`) are stored to `gog_dlcs_{baseGameId}` prefs keyed by base game. `GogGameDetailActivity` shows owned DLC list with "Owned" badge. Note: GOG gen2 installs include owned DLC depots automatically (no separate install needed).

### EPIC-4: DLC Management (v3.0.3-pre)
DLC `baseGameCatalogItemId` captured from `mainGameItem.id` in catalog enrichment. `epic_dlcs_{baseCatalogItemId}` written during sync. `EpicGameDetailActivity` shows DLC list with Install/Reinstall button. Install uses same `EpicDownloadManager` pipeline with DLC's ns/cat/appName.

### AMAZON-2: DLC Management (v3.0.3-pre)
Best-effort DLC detection in `parseEntitlement()` — probes `product.productType`, `product.parentProductId`, and related fields. DLCs separated from base games in sync; `amazon_dlcs_{parentProductId}` written to prefs. `AmazonGameDetailActivity` shows Install button using `AmazonDownloadManager`. Note: detection is best-effort — field names vary by region/product.

---

## BH-Lite Port Tracker

| Feature | BH Status | BH-Lite Port Status | Notes |
|---------|-----------|---------------------|-------|
| D-1 Full-screen detail pages | ✅ v3.0.1-pre | ⬜ | |
| D-2 HTML description strip | ✅ v3.0.1-pre | ⬜ | |
| D-3 Install size | ✅ v3.0.1-pre | ⬜ | |
| D-5 Release date | ✅ v3.0.1-pre | ⬜ | |
| D-6 Ratings | ✅ v3.0.2-pre | ⬜ | GOG only |
| GOG-2 Update Checker | ✅ v3.0.1-pre | ⬜ | |
| GOG-3 DLC Management | ✅ v3.0.3-pre | ⬜ | |
| GOG-1 Cloud Saves | ✅ v3.0.4-pre | — | After BH release |
| GOG-4 GOG Connect | ❌ | — | Discontinued by GOG |
| EPIC-1 Free Games | ✅ v3.0.2-pre | ⬜ | |
| EPIC-3 Update Checker | ✅ v3.0.1-pre | ⬜ | |
| EPIC-4 DLC Management | ✅ v3.0.3-pre | ⬜ | |
| EPIC-2 Cloud Saves | ✅ v3.0.4-pre | — | After BH release |
| AMAZON-1 Update Checker | ✅ v3.0.1-pre | ⬜ | |
| AMAZON-2 DLC Management | ⚠️ v3.0.3-pre | ⬜ | Best-effort detection |
