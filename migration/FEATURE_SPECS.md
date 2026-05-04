# BannerHub Feature Specifications

**BannerHub v3.1.x** — GameHub 5.3.5 ReVanced with extended PC game store integrations, performance tools, and community features.

Generated: 2026-04-23 — Implementation-independent behavioral specs suitable for full codebase rewrite.

---

## 1. GOG Games Library

**What it does:** Provides access to your entire GOG library directly in BannerHub. Log in with your GOG account, browse your owned games, and download and launch them through Wine on Android.

**Inputs:** GOG account credentials (OAuth2 webview); game selection; Install/Launch/Uninstall actions

**Outputs:** Authenticated session persists across app restarts. Games display as cards with cover art, developer, install status. Downloaded games show "Installed" checkmark and "Launch" button. Post-install exe picker dialog if multiple qualifying .exe files found.

**UI entry point:** Left side menu → GOG

**Dependencies:** Internet; GOG account; storage space

---

## 2. GOG Authentication

**What it does:** Securely authenticates with GOG using OAuth2. Tokens stored locally and auto-refreshed before expiry.

**Inputs:** One-time GOG login credentials (email, password, 2FA if enabled)

**Outputs:** Access token + refresh token stored in bh_gog_prefs SharedPreferences. Session survives restarts. Auto-refresh triggered silently before each API call. Logout clears all tokens.

**UI entry point:** First visit to GOG tab shows login screen

**Dependencies:** Internet; WebView

---

## 3. GOG Library Sync

**What it does:** Fetches complete GOG game library including Generation 1 (pre-Galaxy) and Generation 2 (Galaxy) games with full metadata.

**Inputs:** Manual refresh (↺) or automatic on first open

**Outputs:** All owned games loaded with cover art, title, developer, download size, Gen1/Gen2 badge, install status.

**UI entry point:** GOG library list/grid view; refresh button in header

**Dependencies:** Valid GOG tokens; internet

---

## 4. GOG Download Pipeline (Gen 2)

**What it does:** Downloads Generation 2 games using GOG's modern depot manifest system with real-time progress.

**Inputs:** Tap "Install" on Gen 2 game → confirm dialog (shows size, storage check)

**Outputs:** Progress bar with per-file progress (filename, %, MB/s). Cancel button with partial cleanup. On completion: "Add Game" button pre-fills game path in GameHub's EditImportedGameInfoDialog. Green ✓ checkmark on card.

**UI entry point:** Game card "Install" button → confirmation → progress

**Dependencies:** Storage space; internet; GOG session

---

## 5. GOG Download Pipeline (Gen 1 & Installer Fallback)

**What it does:** For legacy GOG games, downloads using Generation 1 byte-range system or direct installer fallback. Supports resumable downloads.

**Inputs:** Tap "Install" on Gen 1 or ancient game → confirm

**Outputs:** Same progress UI as Gen 2. Files assembled into install directory. Resumable (complete files skipped on retry). "Add Game" button on completion.

**UI entry point:** Game card "Install" button (auto-detected as Gen1)

**Dependencies:** Storage space; internet; GOG session

---

## 6. GOG Post-Install Management

**What it does:** After install: re-select executable, copy to Downloads, or uninstall. Launch opens GameHub's game editor with exe pre-filled.

**Inputs:** Launch → auto-selects exe or shows picker. "Set .exe" to re-scan. "Copy to Downloads" → copies folder. Swipe/long-press → "Uninstall" → confirmation.

**Outputs:** Launch passes exe path to EditImportedGameInfoDialog. Exe picker if 2+ qualifying executables found. Copy creates accessible copy in Downloads/. Uninstall removes directory, clears all prefs, resets card.

**UI entry point:** Game card when installed (Launch/Copy/Uninstall buttons); game detail screen

**Dependencies:** Installed game directory; storage (for copy)

---

## 7. GOG Cloud Saves

**What it does:** Back up and restore game save files between device and GOG's cloud servers.

**Inputs:** Game detail → CLOUD SAVES section. First time: "Browse" → in-app folder picker → navigate to save directory → "Select this folder". Then "Upload Saves" or "Download Saves".

**Outputs:** Save folder path persists in prefs (gog_save_dir_{gameId}). Upload compares local vs cloud last_modified timestamps; uploads only newer files. Download overwrites local saves with cloud versions. Status line: "Uploaded N files" / "Downloaded N files" / "Already up to date" / "No cloud saves found".

**UI entry point:** GOG game detail → CLOUD SAVES section → Browse / Upload / Download buttons

**Dependencies:** GOG session; game installed with accessible save directory; internet

---

## 8. GOG Update Checker

**What it does:** Checks if a newer version of an installed GOG game is available. Shows current build ID and provides one-tap update.

**Inputs:** Game detail → UPDATES section → "Check for Updates" → "Update Now"

**Outputs:** Fetches latest build ID, compares with installed. Shows "Up to date ✓" or "Update available!" + button. Update uses same install pipeline as fresh install.

**UI entry point:** GOG game detail → UPDATES section

**Dependencies:** Game installed; internet; GOG session

---

## 9. GOG DLC Management

**What it does:** Shows owned DLC for games with downloadable content. DLCs install alongside base game.

**Inputs:** Game detail → DLC section → "Install" on any DLC

**Outputs:** Lists DLCs with "Owned" badge. Gen2 installs include owned DLC depots automatically. Progress and completion same as base game install.

**UI entry point:** GOG game detail → DLC section

**Dependencies:** Game detail loaded; internet; storage

---

## 10. Epic Games Store Library

**What it does:** Access your entire Epic Games Store library including free monthly games.

**Inputs:** Epic account credentials (OAuth2 webview); game selection

**Outputs:** Session persists. Games display with cover art, developer, install status. Free games section shows weekly offerings.

**UI entry point:** Left side menu → Epic Games; "FREE" button in header

**Dependencies:** Internet; Epic account; storage

---

## 11. Epic Authentication

**What it does:** OAuth2 authentication with Epic. Tokens auto-refresh silently.

**Inputs:** One-time Epic login (email/password + optional 2FA)

**Outputs:** Access + refresh tokens stored in bh_epic_prefs. Session survives restarts. Auto-refresh before API calls. Logout clears tokens.

**UI entry point:** First visit to Epic tab shows login screen

**Dependencies:** Internet; WebView with JavaScript support

---

## 12. Epic Library Sync

**What it does:** Fetches owned games and enriches with catalog metadata (description, cover art, DLC detection, offline flag).

**Inputs:** Manual refresh or automatic on first open

**Outputs:** All owned games loaded with full metadata. DLC detection and CanRunOffline flag cached. Download size lazy-loaded then cached.

**UI entry point:** Epic library list/grid view

**Dependencies:** Epic authentication; internet

---

## 13. Epic Download Pipeline

**What it does:** Downloads games in 6 parallel chunks from Epic's CDN with SHA-1 validation per chunk.

**Inputs:** Tap "Install" → confirm dialog

**Outputs:** 6 parallel download threads with per-file progress (filename, MB/s). Cancel button with cleanup. "Add Game" button on completion. Green ✓ checkmark on card.

**UI entry point:** Game card "Install" button

**Dependencies:** Storage; internet; Epic session

---

## 14. Epic Free Games Browser

**What it does:** Dedicated full-screen activity showing currently-free and upcoming free Epic games.

**Inputs:** Green "FREE" button in Epic library header; tap any free game card

**Outputs:** Opens Epic Store page in system browser. Games sorted into "FREE THIS WEEK" and "FREE COMING SOON" sections. No authentication required.

**UI entry point:** Epic library header "FREE" button → FreeGamesActivity

**Dependencies:** Internet; system web browser

---

## 15. Epic Update Checker

**What it does:** Checks for available updates for installed Epic games.

**Inputs:** Game detail → UPDATES section → "Check for Updates" → "Update Now"

**Outputs:** Fetches manifest buildVersion, compares with installed. Shows status + "Update Now" button if available. Update re-runs install pipeline.

**UI entry point:** Epic game detail → UPDATES section

**Dependencies:** Game installed; internet; Epic session

---

## 16. Epic Cloud Saves

**What it does:** Back up saves to Epic's cloud server. Requires manual save folder setup per game.

**Inputs:** Game detail → CLOUD SAVES → "Browse" → folder picker → select save directory. Then "Upload Saves" / "Download Saves".

**Outputs:** Path persists in prefs (epic_save_dir_{appName}). Upload compares timestamps, uploads newer files. Download overwrites local saves. Status line with count or "Already up to date". Background thread with live UI updates.

**UI entry point:** Epic game detail → CLOUD SAVES section

**Dependencies:** Epic session; game installed; internet

---

## 17. Epic DLC Management

**What it does:** Shows owned Epic DLC and allows separate installation.

**Inputs:** Game detail → DLC section → "Install" on DLC

**Outputs:** DLC cards with Install/Reinstall button. Progress inline during download. Same completion as base game.

**UI entry point:** Epic game detail → DLC section

**Dependencies:** Game detail loaded; internet; storage

---

## 18. Amazon Games Library

**What it does:** Access Amazon Games entitlements. Log in with Amazon account to see all owned titles.

**Inputs:** Amazon account credentials (PKCE OAuth2 webview); game selection

**Outputs:** Session persists. Games display with cover art and install status. Handles 2FA/OTP transparently.

**UI entry point:** Left side menu → Amazon Games

**Dependencies:** Internet; Amazon account with game entitlements; storage

---

## 19. Amazon Authentication

**What it does:** PKCE-secured authentication with Amazon. Handles 2FA/OTP transparently.

**Inputs:** One-time Amazon login + optional OTP/2FA

**Outputs:** Tokens stored in bh_amazon_prefs. Session survives restarts. Auto-refresh before API calls. Logout clears tokens.

**UI entry point:** First visit to Amazon tab shows login screen

**Dependencies:** Internet; WebView

---

## 20. Amazon Library Sync

**What it does:** Queries Amazon's GetEntitlements API to fetch all owned games with metadata.

**Inputs:** Manual refresh or automatic on first open

**Outputs:** All entitlements loaded with title, SKU, product ID, cover art. Download size lazy-loaded and cached.

**UI entry point:** Amazon library list/grid view

**Dependencies:** Amazon authentication; internet

---

## 21. Amazon Download Pipeline

**What it does:** Downloads Amazon games using manifest.proto protobuf format with 6 parallel threads and SHA-256 verification.

**Inputs:** Tap "Install" → confirm dialog

**Outputs:** 6 parallel threads with per-file progress (filename, MB/s). SHA-256 checksum validated per file. Resumable (complete files skipped on retry). "Add Game" on completion.

**UI entry point:** Game card "Install" button

**Dependencies:** Storage; internet; Amazon session

---

## 22. Amazon SDK DLL Deployment

**What it does:** Automatically deploys required FuelSDK and AmazonGamesSDK DLLs to the game directory at launch.

**Inputs:** Launch an Amazon game (automatic)

**Outputs:** FuelSDK_x64.dll and AmazonGamesSDK_* DLLs copied to game directory. FuelPump environment variables set at launch.

**UI entry point:** Automatic at game launch

**Dependencies:** Game installed; DLL files in app bundle

---

## 23. Amazon Update Checker

**What it does:** Checks for updated Amazon games.

**Inputs:** Game detail → UPDATES → "Check for Updates"

**Outputs:** Fetches latest versionId from GetGameDownload API. Compares with installed. Shows status + button if available.

**UI entry point:** Amazon game detail → UPDATES section

**Dependencies:** Game installed; internet; Amazon session

---

## 24. Amazon DLC Management

**What it does:** Shows DLC for Amazon games and allows installation.

**Inputs:** Game detail → DLC section → "Install" on DLC

**Outputs:** Lists DLCs with Install button. Install uses same pipeline as base game. Progress shown inline.

**UI entry point:** Amazon game detail → DLC section

**Dependencies:** Game detail loaded; internet

---

## 25. Component Manager

**What it does:** Full management interface for Wine components (DXVK, VKD3D, Box64, FEXCore, GPU Drivers). View all installed components, inject new ones, backup, and remove.

**Inputs:** Tap card to inject; long-press/swipe for backup/remove; "Add New" to inject as new slot; "Remove All" to clear all BannerHub-managed components.

**Outputs:** List of installed components with type-color badges (DXVK blue, VKD3D purple, Box64 green, etc.). Source badge for downloaded components. Component name + injected filename. Install count header.

**UI entry point:** Left side menu → Components

**Dependencies:** Component files (WCP/ZIP); writable component directory

---

## 26. Component Inject & Add New

**What it does:** Replace a component's contents or add a brand new component slot. Supports WCP (Zstd tar or XZ tar) and ZIP formats.

**Inputs:** Tap card (existing component) or "Add New" → file picker → select WCP or ZIP → confirmation if injecting into existing.

**Outputs:** Component folder cleared before injection (no stale files). File extracted to component directory. Component appears immediately in GameHub's DXVK/VKD3D/Box64/FEXCore/GPU Driver pickers. Injected filename label on card. Persists across restarts.

**UI entry point:** Card tap → file picker; "Add New" button → file picker

**Dependencies:** Valid WCP or ZIP file with correct magic bytes; write access to component directory

---

## 27. Component Backup & Remove

**What it does:** Backup a component to Downloads or completely remove it.

**Inputs:** Swipe RIGHT → backup (copies to Downloads/BannerHub/{name}/). Swipe LEFT → remove (confirmation). Long-press → menu with both options.

**Outputs:** Backup copies component folder recursively. Remove unregisters from GameHub's map, deletes folder from disk, clears downloaded indicator in online repo browser. "Remove All" removes only BannerHub-managed components (stock components never touched).

**UI entry point:** Swipe gestures on component cards; long-press context menu

**Dependencies:** Component must be BannerHub-managed (has source badge)

---

## 28. Component Format Support

**What it does:** Automatically detects and extracts component files in ZIP, Zstd-compressed tar, and XZ-compressed tar formats.

**Inputs:** Component file (format detection by magic bytes)

**Outputs:** ZIP (PK magic): flat extraction. Zstd tar (28 B5 2F FD): FEXCore → flat; DXVK/VKD3D/Box64 → preserve system32/syswow64 structure. XZ tar (FD 37 7A 58): same as Zstd path. Background extraction with progress. All errors surfaced to UI.

**UI entry point:** Automatic during component inject/add

**Dependencies:** Bundled extraction libraries (commons-compress, zstd-jni, tukaani xz)

---

## 29. In-App Component Downloader

**What it does:** Browse and download components directly from built-in GitHub sources. Downloaded components auto-inject as new component slots.

**Inputs:** Component Manager → "Download" button → 3-level navigation: Repo → Category → Asset

**Outputs:** Repos: Arihany WCPHub, The412Banner Nightlies, Kimchi/StevenMXZ/MTR/Whitebelyash GPU Drivers. Categories: DXVK/VKD3D/Box64/FEXCore/GPU Driver. Assets: all versions with file size; installed components show checkmark. Progress: "Downloading: <filename>". Auto-injects after download.

**UI entry point:** Component Manager → "Download" button

**Dependencies:** Internet; GitHub API; writable cache directory

---

## 30. BCI Launcher Button

**What it does:** One-tap launcher for the BannersComponentInjector companion app.

**Inputs:** Tap banner icon in GameHub's top-right toolbar

**Outputs:** Opens com.banner.inject if installed. Shows toast "BannersComponentInjector not installed" if BCI absent.

**UI entry point:** Top-right toolbar banner icon

**Dependencies:** BCI app installed (com.banner.inject)

---

## 31. Winlator HUD — Normal Mode

**What it does:** Minimal in-game performance overlay showing FPS, frame time, and render resolution.

**Inputs:** In-game sidebar → Performance tab → "Winlator HUD" toggle. Drag to reposition. Tap to toggle vertical/horizontal. Opacity slider (0–100%).

**Outputs:** Overlay shows: FPS, frame time (ms + live graph), resolution. Text shadow auto-applied at opacity < 30%. Position, orientation, opacity persisted across sidebar reopens.

**UI entry point:** In-game sidebar → Performance tab → "Winlator HUD" toggle

**Dependencies:** Game running in Wine container; readable /proc/stat

---

## 32. Winlator HUD — Extra Detailed Mode

**What it does:** Expanded performance overlay with CPU, GPU, memory, thermal, and battery metrics.

**Inputs:** In-game sidebar → Performance tab → "Extra Detailed" checkbox. Orientation toggle. Opacity slider.

**Outputs:** Overlay shows (horizontal or vertical): FPS + frame-time graph, CPU%, GPU%, RAM (used/total GB), SWAP (used/total GB), CPU temp, GPU temp, battery temp. "Extra Detailed" grayed out when HUD toggle off. Layout persists.

**UI entry point:** In-game sidebar → Performance tab → "Extra Detailed" checkbox

**Dependencies:** Game running; thermal zone files in /sys/; /proc/meminfo

---

## 33. Winlator HUD — Konkr Style Mode

**What it does:** Strategy game-style HUD with 2-column table (vertical) or compact strip (horizontal). Mutually exclusive with Extra Detailed.

**Inputs:** In-game sidebar → "Konkr Style" checkbox. Tap HUD to toggle layout. Drag to reposition. Opacity slider.

**Outputs:**
- Vertical: FPS (large), CPU%+temp, per-core MHz (C0–C7), GPU%+temp+name+clock+resolution, MODE/SKN/PWR, RAM, SWAP, BAT (with proportional fill bar), TIME
- Horizontal: FPS block, CPU 2×4 core grid, GPU block, thermal/power block, memory block
- Position, orientation, opacity persisted.

**UI entry point:** In-game sidebar → Performance tab → "Konkr Style" checkbox

**Dependencies:** Game running; thermal zones; sysfs CPU freq; KGSL GPU clock; battery /sys/

---

## 34. Sustained Performance Mode

**What it does:** Forces all CPU cores to `performance` governor, eliminating CPU downclocking. WARNING: generates heat. Requires root.

**Inputs:** In-game sidebar → Performance tab → "Sustained Performance Mode" toggle

**Outputs:** On: all cores set to `performance` governor via su. Off: all cores restored to `schedutil`. State persists. Auto-re-applied on sidebar reopen. Greyed out on non-rooted devices.

**UI entry point:** In-game sidebar → Performance tab

**Dependencies:** Root access (grant once via Settings → Advanced); /sys/devices/system/cpu/*/cpufreq/scaling_governor writable

---

## 35. Max Adreno Clocks

**What it does:** Locks Qualcomm Adreno GPU clock floor equal to ceiling, preventing GPU downclocking. WARNING: generates heat. Requires root.

**Inputs:** In-game sidebar → Performance tab → "Max Adreno Clocks" toggle

**Outputs:** On: reads max_freq, writes to min_freq on KGSL devfreq interface. Off: writes 0 to min_freq (removes floor). State persists. Auto-re-applied on sidebar reopen. Greyed out on non-rooted devices.

**UI entry point:** In-game sidebar → Performance tab

**Dependencies:** Root access; /sys/class/kgsl/kgsl-3d0/devfreq/ writable; Adreno GPU

---

## 36. RTS Touch Controls

**What it does:** Gesture overlay for PC strategy/RTS games. Maps touch gestures to mouse actions inside Wine.

**Inputs:** In-game sidebar → Controls tab → toggle enabled. Gear icon to configure pan/zoom directions.

**Outputs:** Single tap → move + left-click. Drag → hold LMB (box selection). Long press 300ms → right-click. Double tap (250ms/50px) → double left-click. Two-finger pan → camera pan (direction configurable). Pinch-to-zoom → mouse wheel (direction configurable). Config persists.

**UI entry point:** In-game sidebar → Controls tab

**Dependencies:** Game running in Wine; touch input device

---

## 37. VRAM Limit Unlock

**What it does:** Extends VRAM options beyond GameHub's default 512MB–4GB range.

**Inputs:** PC game settings → "VRAM Limit" picker

**Outputs:** New options: 512MB, 1GB, 2GB, 4GB (original) + 6GB, 8GB, 12GB, 16GB (new). Selection saved to per-game prefs. Applied to container on launch.

**UI entry point:** PC game settings → VRAM Limit dropdown

**Dependencies:** Device with available system RAM; Wine container VRAM allocation support

---

## 38. Per-Game CPU Core Affinity

**What it does:** Pin game process to specific CPU cores. Multi-select dialog for precise core selection.

**Inputs:** PC game settings → "Core Count" (replaced with affinity picker). Multi-select checkboxes for cores 0–7. Core grouping labels: Efficiency (0–3), Performance (4–6), Prime (7). "Apply" saves. "No Limit" clears affinity.

**Outputs:** Selected cores saved as bitmask in per-game prefs. Game process pinned to selected cores at launch. All 8 cores = "No Limit". Settings row updated immediately on apply.

**UI entry point:** PC game settings → Core Count row → affinity picker dialog

**Dependencies:** WINEMU_CPU_AFFINITY environment variable support in Wine container

---

## 39. Offline Game Settings Access

**What it does:** Game settings remain fully accessible and editable while offline. No blocking spinner or error.

**Inputs:** Open PC game settings while offline

**Outputs:** Settings load from local SharedPreferences. Container list shows empty (no fresh fetch). Component pickers show cached or empty list. All toggles, sliders, text fields fully functional. Changes saved normally. No error dialogs.

**UI entry point:** PC game settings (works identically online/offline)

**Dependencies:** Game installed once (local prefs exist)

---

## 40. Offline Steam Skip

**What it does:** When Steam auto-login fails at cold start (no network), detects condition and skips Steam login screen, using cached session.

**Inputs:** Launch BannerHub with no network (automatic behavior)

**Outputs:** No Steam login screen. Proceeds with cached session. Already-installed Steam games remain launchable. Auto-login resumes when network restored.

**UI entry point:** Automatic on app cold start

**Dependencies:** Previous Steam login cached; Steam library data cached

---

## 41. Settings: Advanced Tab

**What it does:** Power-user settings and system integration controls.

**Inputs:** Settings → Advanced tab. Toggle switches and buttons.

**Outputs:** EmuReady API toggle. CPU Usage Display toggle. Performance Metrics toggle. Sustained Performance Mode toggle (same as sidebar). "Grant Root Access" button → warning dialog → runs su -c id → stores result → enables/greys out root toggles throughout app.

**UI entry point:** Settings → Advanced tab

**Dependencies:** Root access button requires device with su command

---

## 42. Community Configs — Games Browser (Screen 1)

**What it does:** Searchable list of all games with community-shared configurations. Shows config count per game.

**Inputs:** Left side menu → Game Configs. Search box to filter. Tap game to see configs.

**Outputs:** Games listed alphabetically with config count badge. Search filters in real-time ("X of Y games" label). Header shows device model, SOC/GPU, total game count. Tapping game navigates to Configs list (Screen 2).

**UI entry point:** Left side menu → "Game Configs"

**Dependencies:** Internet (games.json refresh every 30 min); Cloudflare Worker + GitHub online

---

## 43. Community Configs — Configs List (Screen 2)

**What it does:** Lists all shared configs for selected game with SOC filtering, device/date labels, age indicator, and voting.

**Inputs:** Selected game from Screen 1. SOC filter chips (horizontal scrollable). "All" chip (default). Tap config card to open detail. Upvote button.

**Outputs:** Config cards show: device model, SOC, upload date, vote count, download count. SOC filter chips from unique SOC values. Configs older than 6 months show amber "may be outdated" label. ✓ My SOC badge (green) for configs from same GPU. Sorted newest first.

**UI entry point:** Screen 1 game selection → Screen 2; SOC chips; config cards

**Dependencies:** Internet; game configs from GitHub

---

## 44. Community Configs — Config Detail & Actions (Screen 3)

**What it does:** Full config details with metadata, inline settings/components view, and download/share/report/comment options.

**Inputs:** Tapped config from Screen 2. Action buttons: Download, View Settings, Share, Report, Comments, Apply to Game.

**Outputs:** Info card: device, SOC, BH version, settings count, components count, uploader description, verified SOC badge. Download to /sdcard/BannerHub/configs/. Inline settings/component view. Share copies GitHub download URL to clipboard. Report flags config. Comments: read + post. "Apply to Game...": downloads + opens game picker + shows missing component dialog if needed.

**UI entry point:** Config card tap from Screen 2

**Dependencies:** Internet; local storage (for download)

---

## 45. Community Configs — My Uploads (Screen 4)

**What it does:** List of all configs uploaded by current user. Edit descriptions and delete uploads.

**Inputs:** Screen 1 header → "My Uploads". Long-press any config → "Delete Upload". Tap config → detail with "Delete My Upload" button.

**Outputs:** Lists all configs uploaded in session (from bh_config_uploads SP). Each entry: game name, date, vote/download counts. Delete → removes from community + clears local SP record. Edit Description (token-authenticated, original uploader only).

**UI entry point:** Screen 1 "My Uploads" button

**Dependencies:** Upload token (stored in bh_config_uploads SP); internet

---

## 46. In-App Folder Picker

**What it does:** Navigate device filesystem to select directories. Used for cloud save setup and config imports.

**Inputs:** Browse button in cloud save sections. Navigate directories (tap to enter). "↑ Up" to go to parent. "Select this folder" to confirm.

**Outputs:** Returns selected path via setResult(RESULT_OK). Current path shown in header (truncated to 2 segments). Files hidden; only directories shown.

**UI entry point:** Cloud Save sections (GOG/Epic) → Browse button; any file-selecting dialog

**Dependencies:** Readable filesystem; Activity context

---

## 47. Per-Game Config Export

**What it does:** Export current game settings and installed components to JSON. Save locally or share to community.

**Inputs:** PC game settings → "Export Config". Preview dialog shows: device, SOC, settings count, components count. Choose: "Save Locally" or "Save Locally + Share Online".

**Outputs:** Local save: /sdcard/BannerHub/configs/GameName-Manufacturer-Model-SOC-UnixTimestamp.json. Online share: same file + uploads to Cloudflare Worker → GitHub. Shared config visible in community browser. Manually sideloaded components without tracked URLs are skipped.

**UI entry point:** PC game settings → "Export Config" button

**Dependencies:** Storage write permission; internet (for online share)

---

## 48. Per-Game Config Import

**What it does:** Import saved game configs from device or community. Auto-downloads missing components.

**Inputs:** PC game settings → "Import Config". Two tabs: "My Device" (files from /sdcard/BannerHub/configs/) and "Browse Community". SOC mismatch warning. Missing component auto-download prompt.

**Outputs:** Preview card: device, SOC, settings count, components count. SOC mismatch shows ⚠ warning. Missing component list with dialog: "Skip" or "Download All". Downloads missing components. Applies settings after. Per-game SharedPreferences updated with all config values.

**UI entry point:** PC game settings → "Import Config" button

**Dependencies:** Config JSON file; internet (for component downloads); storage

---

## 49. Config Cross-Compatibility (BannerHub Lite)

**What it does:** Configs from BannerHub are fully compatible with BannerHub Lite and vice versa. Both apps share same format and storage location.

**Inputs:** Exported config JSON from either app

**Outputs:** Both apps write/read /sdcard/BannerHub/configs/. Both use pc_g_setting<gameId> SharedPreferences. app_source field ("bannerhub" or "bannerhub_lite") for tracking only. Configs fully interchangeable.

**UI entry point:** Export/Import dialogs (automatic format detection)

**Dependencies:** Both apps installed (for cross-import testing)

---

## 50. Wine Task Manager

**What it does:** Real-time monitoring and control of Wine session while game is running.

**Inputs:** In-game sidebar → Wine Task Manager. Four tabs: Container Info, Applications, Processes, Launch. Kill buttons. Auto-refresh every 3 seconds.

**Outputs:**
- Container Info: CPU cores (WINEMU_CPU_AFFINITY), RAM (/proc/meminfo), VRAM (prefs), device model, Android version
- Applications: all wine* host processes with PID + kill button
- Processes: all .exe guest processes with PID + kill button
- Launch: WINEPREFIX file browser; tap directories (yellow ▶) to navigate; tap .exe/.msi/.bat/.cmd (white) to launch
- Launch guard prevents session-complete callback from terminating game when secondary exe closes (released 3s after secondary exits)
- All tabs refresh every 3 seconds

**UI entry point:** In-game sidebar → Wine Task Manager

**Dependencies:** Game running in Wine; readable /proc/; accessible WINEPREFIX directory

---

## 51. Component Descriptions in Game Settings

**What it does:** Components installed via BannerHub show description text in per-game component pickers.

**Inputs:** PC game settings → any component picker (DXVK, VKD3D, Box64, FEXCore, GPU Driver)

**Outputs:** Description sourced from WCP profile.json or ZIP meta.json, cached at inject time. Shown below component name in picker dropdown. Only BannerHub-managed components have descriptions.

**UI entry point:** PC game settings → component picker dropdowns

**Dependencies:** Component metadata files present in component directory

---

## 52. Japanese Locale Support

**What it does:** Full Japanese translation of entire BannerHub app when Android system language is set to Japanese.

**Inputs:** Android Settings → Language → select Japanese

**Outputs:** Complete 3,468-string Japanese translation active. All screens, dialogs, buttons, labels in Japanese. English users unaffected. No in-app switcher needed.

**UI entry point:** Android system language setting (automatic)

**Dependencies:** Android system language set to Japanese

---

## 53. Virtual Container Cleanup on Uninstall

**What it does:** When a game is uninstalled, its Wine virtual container directory is fully cleaned up.

**Inputs:** Uninstall game via GameHub (automatic)

**Outputs:** virtual_containers/{gameId}/ directory fully deleted. No orphaned container directories. Storage freed immediately.

**UI entry point:** GameHub game uninstall (automatic)

**Dependencies:** Writable virtual_containers directory

---

## 54. UI Tweaks

**What it does:** Minor UI improvements for clarity and usability.

**Outputs:** Bottom navigation bar "My" tab renamed to "My Games". Header titles updated where relevant. Menu labels clarified.

**UI entry point:** Bottom navigation bar; app menu

**Dependencies:** None

---

## 55. Controller Navigation Support

**What it does:** Full D-pad and gamepad controller support for navigating store library activities.

**Inputs:** Game controller D-pad / analog stick / buttons. A to select, B to go back, D-pad to navigate.

**Outputs:**
- List view: D-pad up/down; focused card shows gold 3dp border + lighter background
- Grid/poster view: D-pad all 4 directions; focused tile shows gold border via foreground overlay (works with rounded corners)
- Header buttons: focusable with gold 2dp border + lighter fill on focus
- Focus highlight consistently uses gold (#FFD700) across all stores

**UI entry point:** Store library activities (GOG/Epic/Amazon list/grid views); header navigation buttons

**Dependencies:** Controller input device; GameHub's existing controller input system

---

## 56. APK Variants (9 total)

**What it does:** BannerHub available in 9 APK variants with different package names, allowing multiple installations and package spoofing.

**Outputs:**
| Variant | Package Name |
|---------|-------------|
| Normal | banner.hub |
| Normal.GHL | gamehub.lite |
| PuBG | com.tencent.ig |
| AnTuTu | com.antutu.ABenchMark |
| alt-AnTuTu | com.antutu.benchmark.full |
| PuBG-CrossFire | com.tencent.tmgp.cf |
| Ludashi | com.ludashi.aibench |
| Genshin | com.miHoYo.GenshinImpact |
| Original | com.xiaoji.egggame |

All signed with AOSP testkey (v1/v2/v3). All can coexist simultaneously.

**UI entry point:** Release download page; app switcher

**Dependencies:** Enough storage; Android support for multiple apps

---

## Summary Table

| Feature | Requires Root | Requires Internet | Requires Game Install |
|---------|---------------|-------------------|-----------------------|
| GOG / Epic / Amazon (all) | No | Yes | No (except download) |
| Component Manager | No | No (except download) | No |
| Winlator HUD (all modes) | No | No | Yes |
| RTS Controls | No | No | Yes |
| Sustained Performance Mode | **Yes** | No | Yes |
| Max Adreno Clocks | **Yes** | No | Yes |
| VRAM Unlock | No | No | No |
| CPU Core Affinity | No | No | No |
| Offline Game Settings | No | No | Yes |
| Offline Steam Skip | No | No | Yes |
| Community Configs | No | Yes (optional) | No |
| Cloud Saves (GOG/Epic) | No | Yes | Yes |
| Controller Navigation | No | No | No |
| Japanese Locale | No | No | No |
| Wine Task Manager | No | No | Yes |
| APK Variants | No | No | No |
