# BannerHub Injection Point Map

**Target:** GameHub 5.3.5 (ReVanced)  
**Package:** gamehub.lite  
**Generated:** 2026-04-23

This document maps every injection point in the BannerHub codebase, which decompiles GameHub 5.3.5 APK (smali bytecode) and applies targeted patches to add alternative game store integrations, component management, HUD overlays, and system utilities.

---

## Architecture Overview

BannerHub operates via four patch layers:

1. **Smali Patches** (`patches/`) — Bytecode modifications to GameHub's classes
2. **Component Manager Patch** (`component-manager-patch/`) — Standalone component framework
3. **Java Extensions** (`extension/`) — Compiled extension classes for GOG, Epic, Amazon, HUD, etc.
4. **Resource Overlays** (`patches/res/`) — Layout and drawable assets

---

## Directory Structure

```
patches/
├── AndroidManifest.xml                     ← Permissions + extension activity declarations
├── smali/                                   ← Flat patches (minimal set)
├── smali_classes*/                          ← Stratified patches by dex index zone
│   ├── smali_classes2/                      ← Settings dialogs
│   ├── smali_classes3/                      ← Game settings view model
│   ├── smali_classes4/                      ← PC game settings operations
│   ├── smali_classes5/                      ← Main UI dialogs
│   ├── smali_classes6/                      ← PrefsandEnvironment
│   ├── smali_classes9/                      ← Resource ID generators
│   ├── smali_classes10/                     ← Launch strategies
│   ├── smali_classes11/                     ← Main launcher activity
│   ├── smali_classes14/                     ← Sidebar fragments
│   ├── smali_classes15/                     ← Wine emulation core
│   └── smali_classes16/                     ← BannerHub extensions (near 65k limit)
└── res/                                     ← Resource overlays (layouts, drawables, strings)

component-manager-patch/patches/
├── smali_classes3/                          ← Game settings view model integration
├── smali_classes5/                          ← Menu dialog integration
└── smali_classes16/                         ← Component Manager core classes

extension/                                   ← Java source (compiled into decompiled APK)
├── *MainActivity.java                       ← Store entry points (GOG, Epic, Amazon)
├── *LoginActivity.java                      ← OAuth flows
├── *GamesActivity.java                      ← Game library UI
├── *GameDetailActivity.java                 ← Game detail/launch screens
├── *ApiClient.java                          ← REST API integrations
├── *DownloadManager.java                    ← Background downloads
├── *CloudSaveManager.java                   ← Cloud save sync
├── Bh*.java                                 ← BannerHub utilities (HUD, settings, wine)
└── ui/GameIdHelper.java                     ← Game ID resolution
```

---

## Injection Points by Category

### 1. COMPONENT MANAGER

**Feature:** Unified management UI for Wine GPU drivers, translation layers (Box64, FEX), and compatibility tools (DXVK, VKD3D).

#### 1.1 Component Manager Activity

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/ComponentManagerActivity.smali` | `ComponentManagerActivity` | New class | Implements complete component browser with RecyclerView, swipe-to-delete, search, and backup/remove/inject actions. |
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/BhComponentAdapter.smali` | `BhComponentAdapter` | New class | RecyclerView adapter with type badges (DXVK/VKD3D/Box64/FEX/GPU), color-coded accent strips, and per-component action handling. |
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/BhSwipeCallback.smali` | `BhSwipeCallback` | New class | ItemTouchHelper callback implementing left swipe = remove, right swipe = backup. |

#### 1.2 Component Injection & Registration

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/ComponentInjectorHelper.smali` | `ComponentInjectorHelper` | New static utils | Extracts .wcp (Zstd/XZ tar), .zip, and .tar archives; reads profile.json/meta.json; registers components with EmuComponents; appends local components to game settings dropdowns. |
| `component-manager-patch/patches/smali_classes3/com/xj/winemu/settings/GameSettingViewModel$fetchList$1.smali` | Game settings callback | +2 lines (line ~2950) | Calls `ComponentInjectorHelper.appendLocalComponents()` to inject locally-installed components (GPU drivers, DXVK, VKD3D, Box64, FEX) into the server list before the UI callback. |

#### 1.3 Component Download Integration

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/ComponentDownloadActivity.smali` | `ComponentDownloadActivity` | New class | 3-level navigation UI: repo selector → category picker (DXVK/VKD3D/Box64/FEX/GPU) → asset list. Downloads from 6 online repos (Arihany, StevenMXZ, Kimchi, MTR, Whitebelyash GPU drivers, The412Banner Nightlies). |
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/ComponentDownloadActivity$*.smali` | Inner classes (1–9) | New classes | GitHub Releases API fetch, pack.json parsers, UI runnables for category display, download-to-cache, injection on UI thread. |
| `patches/smali_classes16/com/xj/landscape/launcher/ui/menu/WcpExtractor.smali` | `WcpExtractor` | New class | Extracts .wcp tar files locally for inject-from-file mode. |

#### 1.4 Menu Integration

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `component-manager-patch/patches/smali_classes5/com/xj/landscape/launcher/ui/menu/HomeLeftMenuDialog.smali` | `HomeLeftMenuDialog` | +10 lines (2 sites) | Adds "Components" menu item (ID=9) to left-side drawer; routes tap to ComponentManagerActivity. |

#### 1.5 AndroidManifest

| File | Activity | What It Does |
|------|----------|--------------|
| `patches/AndroidManifest.xml` | `com.xj.landscape.launcher.ui.menu.ComponentManagerActivity` | Declares activity with landscape orientation, exported=false. |
| `patches/AndroidManifest.xml` | `com.xj.landscape.launcher.ui.menu.ComponentDownloadActivity` | Declares activity with landscape orientation, exported=false. |

---

### 2. GOG INTEGRATION

**Feature:** Login, library sync, game launch, cloud saves, and download management for GOG.com.

#### 2.1 GOG Main Activities

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/GogMainActivity.java` | `GogMainActivity` | New class (app.revanced.extension.gamehub) | Entry point for GOG store; displays login/logout card based on auth token in `bh_gog_prefs` SharedPreferences. Called from side menu (ID=10). |
| `extension/GogLoginActivity.java` | `GogLoginActivity` | New class | OAuth2 flow for GOG.com; stores access_token, username, and user ID in `bh_gog_prefs`. |
| `extension/GogGamesActivity.java` | `GogGamesActivity` | New class | Displays GOG library (sorted, searchable ListView); taps launch via `pending_gog_exe` flag. |
| `extension/GogGameDetailActivity.java` | `GogGameDetailActivity` | New class | Show GOG game metadata, screenshots, launch button. Triggers game launch via `pending_gog_exe`. |

#### 2.2 GOG Backend Services

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/GogApiClient.java` | `GogApiClient` | New class | REST client for GOG API; fetches user library, game metadata, download links. |
| `extension/GogAuthClient.java` | `GogAuthClient` | New class | Manages OAuth2 tokens; handles token refresh. |
| `extension/GogCredentialStore.java` | `GogCredentialStore` | New class | Reads/writes GOG auth tokens to `bh_gog_prefs`. |
| `extension/GogDownloadManager.java` | `GogDownloadManager` | New class | Downloads GOG game installers/builds; integrates with GameHub's download UI. |
| `extension/GogCloudSaveManager.java` | `GogCloudSaveManager` | New class | Syncs game saves with GOG Cloud. |
| `extension/GogLaunchHelper.java` | `GogLaunchHelper` | New class | Launches GOG game executables via Wine. |
| `extension/GogTokenRefresh.java` | `GogTokenRefresh` | New class | Refresh token on expiry; auto-renews. |
| `extension/GogInstallPath.java` | `GogInstallPath` | New class | Manages GOG game installation directory mapping. |

#### 2.3 AndroidManifest

| Activity | What It Does |
|----------|--------------|
| `app.revanced.extension.gamehub.GogMainActivity` | Registered in AndroidManifest.xml with landscape orientation. |
| `app.revanced.extension.gamehub.GogLoginActivity` | Declared. |
| `app.revanced.extension.gamehub.GogGamesActivity` | Declared. |
| `app.revanced.extension.gamehub.GogGameDetailActivity` | Declared. |

---

### 3. EPIC GAMES INTEGRATION

**Feature:** Login, library sync, free games tracking, game launch, cloud saves, and downloads for Epic Games Store.

#### 3.1 Epic Main Activities

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/EpicMainActivity.java` | `EpicMainActivity` | New class (app.revanced.extension.gamehub) | Entry point for Epic; displays login/logout card based on EpicCredentialStore state. Called from side menu (ID=12 / 0xc). |
| `extension/EpicLoginActivity.java` | `EpicLoginActivity` | New class | OAuth2 device flow for Epic Games; stores refresh token. |
| `extension/EpicGamesActivity.java` | `EpicGamesActivity` | New class | Lists owned + free games; taps launch via pending_epic_exe. |
| `extension/EpicGameDetailActivity.java` | `EpicGameDetailActivity` | New class | Epic game metadata, launch controls. |
| `extension/EpicFreeGamesActivity.java` | `EpicFreeGamesActivity` | New class | Dedicated free games tracker; shows Epic's weekly free offerings. |

#### 3.2 Epic Backend Services

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/EpicApiClient.java` | `EpicApiClient` | New class | GraphQL + REST client for Epic API; queries library, free games, game metadata. |
| `extension/EpicAuthClient.java` | `EpicAuthClient` | New class | Device code OAuth2 flow; manages bearer tokens. |
| `extension/EpicCredentialStore.java` | `EpicCredentialStore` | New class | Persists Epic refresh tokens and account ID. |
| `extension/EpicDownloadManager.java` | `EpicDownloadManager` | New class | Manages Epic game installer downloads. |
| `extension/EpicCloudSaveManager.java` | `EpicCloudSaveManager` | New class | Cloud save sync with Epic backend. |

#### 3.3 AndroidManifest

| Activity | What It Does |
|----------|--------------|
| `app.revanced.extension.gamehub.EpicMainActivity` | Registered with landscape orientation. |
| `app.revanced.extension.gamehub.EpicLoginActivity` | Declared. |
| `app.revanced.extension.gamehub.EpicGamesActivity` | Declared. |
| `app.revanced.extension.gamehub.EpicGameDetailActivity` | Declared. |
| `app.revanced.extension.gamehub.EpicFreeGamesActivity` | Declared. |

---

### 4. AMAZON GAMES INTEGRATION

**Feature:** Login, library sync, game launch, and downloads for Amazon Games / Luna.

#### 4.1 Amazon Main Activities

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/AmazonMainActivity.java` | `AmazonMainActivity` | New class (app.revanced.extension.gamehub) | Entry point; login/logout card. Called from side menu (ID=11). |
| `extension/AmazonLoginActivity.java` | `AmazonLoginActivity` | New class | Amazon OAuth PKCE flow for app registration + authorization. |
| `extension/AmazonGamesActivity.java` | `AmazonGamesActivity` | New class | Amazon library browser; taps launch via pending_amazon_exe. |
| `extension/AmazonGameDetailActivity.java` | `AmazonGameDetailActivity` | New class | Amazon game details, launch button. |

#### 4.2 Amazon Backend Services

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/AmazonApiClient.java` | `AmazonApiClient` | New class | REST client for Amazon Games API; fetches library, metadata. |
| `extension/AmazonAuthClient.java` | `AmazonAuthClient` | New class | OAuth2 PKCE flow with Amazon; manages tokens. |
| `extension/AmazonCredentialStore.java` | `AmazonCredentialStore` | New class | Persists Amazon OAuth tokens and account info. |
| `extension/AmazonDownloadManager.java` | `AmazonDownloadManager` | New class | Manages Amazon game installer downloads. |
| `extension/AmazonManifest.java` | `AmazonManifest` | New class | Parses game manifests from Amazon. |
| `extension/AmazonPKCEGenerator.java` | `AmazonPKCEGenerator` | New class | PKCE code challenge/verifier generation. |
| `extension/AmazonSdkManager.java` | `AmazonSdkManager` | New class | Initializes Amazon SDK for device authorization. |

#### 4.3 AndroidManifest

| Activity | What It Does |
|----------|--------------|
| `app.revanced.extension.gamehub.AmazonMainActivity` | Registered with landscape orientation. |
| `app.revanced.extension.gamehub.AmazonLoginActivity` | Declared. |
| `app.revanced.extension.gamehub.AmazonGamesActivity` | Declared. |
| `app.revanced.extension.gamehub.AmazonGameDetailActivity` | Declared. |

---

### 5. HUD OVERLAYS (Performance/Stats Display)

**Feature:** In-game FPS counters, memory usage, GPU info, thermal data, and KonKr-style overlays.

#### 5.1 HUD Framework

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhHudInjector.smali` | `BhHudInjector` | New class | Called from `WineActivity.onResume()`; decides which HUD to show based on prefs (winlator_hud, hud_extra_detail, hud_konkr_style). Creates or updates BhFrameRating / BhDetailedHud / BhKonkrHud views. |

#### 5.2 HUD Implementations

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/BhFrameRating.java` | `BhFrameRating` | New class | Simple 3-line FPS + frame time counter; top-right positioned overlay. |
| `extension/BhDetailedHud.java` | `BhDetailedHud` | New class | Extended HUD: FPS, frame time, GPU, RAM, VRam, CPU load, thermal, network. |
| `extension/BhKonkrHud.java` | `BhKonkrHud` | New class | KonKr-style HUD with animated graphs, color gradients, thermal warnings. |

#### 5.3 HUD Listeners (Sidebar Controls)

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhHudStyleSwitchListener.smali` | `BhHudStyleSwitchListener` | New class | Toggle listener for HUD style switch (basic ↔ detailed). |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhHudKonkrListener.smali` | `BhHudKonkrListener` | New class | Toggle listener for KonKr mode. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhHudExtraDetailListener.smali` | `BhHudExtraDetailListener` | New class | Toggle listener for extra detail (GPU/thermal/network). |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhHudOpacityListener.smali` | `BhHudOpacityListener` | New class | Slider listener for HUD transparency (0.3–1.0). |

#### 5.4 HUD Utilities

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/BhFrameRating.java` | In-class methods | Calculates FPS via frame time history; updates every frame. |
| `extension/BhDetailedHud.java` | In-class methods | Reads /proc/meminfo, /proc/stat, /sys/class/thermal; formats output. |

---

### 6. SIDEBAR & CONTROLS FRAMEWORK

**Feature:** Extended Wine sidebar with task manager, gesture config, input controls, CPU settings, and performance tuning.

#### 6.1 Task Manager Tab

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhTaskManagerFragment.smali` | `BhTaskManagerFragment` | New class | 3-tab Wine task browser: Applications (wine infra), Processes (.exe tasks), Launch (file browser + executable launcher). Auto-refreshes every 3s. Shows container info (CPU, RAM, VRam limits). |

#### 6.2 Gesture Configuration

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/RtsGestureConfigDialog.smali` | `RtsGestureConfigDialog` | New class | Modal dialog for RTS touch control config: gesture picker (4-finger swipe, double-tap, etc.) → action selector (camera pan, right-click, unit select). |
| `patches/smali_classes16/com/xj/winemu/sidebar/RtsGestureConfigDialog$*.smali` | Inner classes | New classes | Listeners for gesture selection, action picking, dialog close, spinners. |
| `patches/smali_classes16/com/xj/winemu/sidebar/RtsGestureSettingsClickListener.smali` | `RtsGestureSettingsClickListener` | New class | Opens RtsGestureConfigDialog from sidebar button. |

#### 6.3 Input Control Enhancements

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/pcvirtualbtn/inputcontrols/InputControlsManager.smali` | `InputControlsManager` | Modified | Integration point for RTS gesture events; routes to wine input injection. |
| `patches/smali_classes16/com/xj/pcvirtualbtn/inputcontrols/RangeScrollerRtsTask.smali` | `RangeScrollerRtsTask` | New class | RTS scroll area handler for camera/unit group range selection. |
| `patches/smali_classes16/com/xj/winemu/view/RtsTouchOverlayView.smali` | `RtsTouchOverlayView` | New class | Transparent overlay capturing multi-touch RTS gestures. |
| `patches/smali_classes16/com/xj/winemu/view/RtsTouchOverlayView$RightClickReleaseRunnable.smali` | Inner runnable | New class | Posts right-click release event on touch up. |

#### 6.4 Sidebar Menu Items & Listeners

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhTabListener.smali` | `BhTabListener` | New class | Generic tab switcher for sidebar fragments. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhTaskClickListener.smali` | `BhTaskClickListener` | New class | Processes kill/task list from task manager. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhInitLaunchRunnable.smali` | `BhInitLaunchRunnable` | New class | Initial file listing load for launch tab. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhExeLaunchListener.smali` | `BhExeLaunchListener` | New class | Launches .exe/.msi from file browser tab. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhFolderListener.smali` | `BhFolderListener` | New class | Navigates folder tree in launch tab. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhBrowseToRunnable.smali` | `BhBrowseToRunnable` | New class | Updates file list UI on folder change. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhApiSelectorListener.smali` | `BhApiSelectorListener` | New class | GPU API selector (D3D11/D3D12/Vulkan). |

#### 6.5 Performance & System Controls

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhPerfSetupDelegate.smali` | `BhPerfSetupDelegate` | New class | Applies performance profile (low/medium/high) to game settings. |
| `patches/smali_classes16/com/xj/winemu/sidebar/RtsSwitchClickListener.smali` | `RtsSwitchClickListener` | New class | Toggle RTS mode on/off from sidebar. |
| `patches/smali_classes16/com/xj/winemu/sidebar/SustainedPerfSwitchClickListener.smali` | `SustainedPerfSwitchClickListener` | New class | Toggle sustained performance mode. |
| `patches/smali_classes16/com/xj/winemu/sidebar/MaxAdrenoClickListener.smali` | `MaxAdrenoClickListener` | New class | Max Adreno GPU clock button. |
| `patches/smali_classes16/com/xj/winemu/settings/CpuMultiSelectHelper.smali` | `CpuMultiSelectHelper` | New class | Dialog for selecting CPU cores for game (pin/unpin individual cores). |
| `patches/smali_classes16/com/xj/winemu/settings/CpuMultiSelectHelper$*.smali` | Inner classes | New classes | Listeners for core selection UI. |

#### 6.6 Root Operations

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes16/com/xj/winemu/sidebar/BhRootGrantHelper.smali` | `BhRootGrantHelper` | New class | Requests root access via su; applies CPU frequency scaling, thermal throttling, I/O scheduler tuning. |
| `patches/smali_classes16/com/xj/winemu/sidebar/BhRootGrantHelper$*.smali` | Inner classes | New classes | Async root command runners, permission check. |

---

### 7. MAIN LAUNCHER & MENU INTEGRATION

**Feature:** Side menu additions, launcher modifications, and component/store entry point routing.

#### 7.1 Main Activity Patching

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes11/com/xj/landscape/launcher/ui/main/LandscapeLauncherMainActivity.smali` | `LandscapeLauncherMainActivity` | Large patch | Added pending game launch checks for GOG, Epic, Amazon (`pending_gog_exe`, `pending_epic_exe`, `pending_amazon_exe`); calls corresponding launch helpers on resume. |
| `patches/smali_classes11/com/xj/landscape/launcher/ui/main/BciLauncherClickListener.smali` | `BciLauncherClickListener` | New class | Launcher for BannersComponentInjector (external component inject app); shows toast if not installed. |

#### 7.2 Side Menu Dialog

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes5/com/xj/landscape/launcher/ui/menu/HomeLeftMenuDialog.smali` | `HomeLeftMenuDialog` | +10 lines injected | Added Components menu entry (ID=9) to left drawer; routes to ComponentManagerActivity. |
| (same file) | `HomeLeftMenuDialog` | Packed-switch update | Extended switch table to handle Components tap. |

#### 7.3 Game Detail Export/Import

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali/com/xj/landscape/launcher/ui/gamedetail/BhExportLambda.smali` | `BhExportLambda` | New class | Exports game config to JSON; used by settings sync feature. |
| `patches/smali/com/xj/landscape/launcher/ui/gamedetail/BhImportLambda.smali` | `BhImportLambda` | New class | Imports game config from JSON; restores settings. |

---

### 8. WINE EMULATION PATCHING

**Feature:** Enhanced Wine configuration, environment control, sidebar integration, and HUD injection.

#### 8.1 Wine Activity & Core

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes15/com/xj/winemu/WineActivity.smali` | `WineActivity` | +5 lines | Calls `BhHudInjector.injectOrUpdate()` in onResume(); injects correct HUD overlay per user prefs. |
| `patches/smali_classes15/com/winemu/core/controller/X11Controller.smali` | `X11Controller` | Modified | RTS touch gesture routing; passes multi-touch events to InputControlsManager. |
| `patches/smali_classes15/com/winemu/core/controller/EnvironmentController.smali` | `EnvironmentController` | Modified | Wine environment variable injection; applies DXVK_HUD, PROTON_*, GPU settings. |

#### 8.2 Sidebar Integration

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes14/com/xj/winemu/sidebar/SidebarControlsFragment.smali` | `SidebarControlsFragment` | Modified | Added tabs for task manager, gesture config, performance settings; wired listeners. |
| `patches/smali_classes3/com/xj/winemu/sidebar/WineActivityDrawerContent.smali` | `WineActivityDrawerContent` | Modified | Integrated with main Wine sidebar; added BannerHub UI elements. |

#### 8.3 Settings & Config

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes4/com/xj/winemu/settings/PcGameSettingOperations.smali` | `PcGameSettingOperations` | Modified | Component selection dropdown integration; shows local + server components. |
| `patches/smali_classes3/com/xj/winemu/settings/GameSettingViewModel$fetchList$1.smali` | Game settings callback | +2 lines | Calls `ComponentInjectorHelper.appendLocalComponents()` before callback. |
| `patches/smali_classes2/com/xj/winemu/settings/SelectAndSingleInputDialog$Companion.smali` | Dialog companion | Modified | Input dialog customization for game settings. |

#### 8.4 Launch Strategy

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes10/com/xj/landscape/launcher/launcher/strategy/SteamGameByPcEmuLaunchStrategy$execute$3.smali` | Steam launch lambda | Modified | Applies per-game component selection (DXVK version, GPU driver, etc.) before launching via Wine. |

---

### 9. PREFERENCES & CONFIGURATION

**Feature:** Persistent settings storage for all integrations and feature toggles.

#### 9.1 GameHub Preferences

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes6/app/revanced/extension/gamehub/prefs/GameHubPrefs.smali` | `GameHubPrefs` | New class | Wrapper for BannerHub preferences; reads/writes: `bh_prefs` (HUD toggles, opacity, style), `bh_gog_prefs`, `bh_epic_prefs`, `bh_amazon_prefs`, `banners_sources` (component download origin tracking). |

#### 9.2 Game-Specific Prefs

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `patches/smali_classes10/com/xj/landscape/launcher/ui/setting/holder/SettingSwitchHolder.smali` | Settings toggle UI | Modified | Component selection switches; persists chosen DXVK/VKD3D/Box64/FEX/GPU versions per game. |

---

### 10. UTILITY & HELPER CLASSES

#### 10.1 Game ID Resolution

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/ui/GameIdHelper.java` | `GameIdHelper` | New class | Maps GameHub game IDs to GOG/Epic/Amazon store IDs; helps launch the right game on the right store. |
| `patches/smali_classes5/app/revanced/extension/gamehub/ui/GameIdHelper.smali` | (smali version) | New class | Smali port of GameIdHelper. |

#### 10.2 Settings Export

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/BhSettingsExporter.java` | `BhSettingsExporter` | New class | Exports all BannerHub game configs (HUD prefs, component choices, GOG/Epic/Amazon mappings) to JSON for backup/share. |
| `extension/BhGameConfigsActivity.java` | `BhGameConfigsActivity` | New class | UI for game configuration export/import. |

#### 10.3 Wine Launch Helper

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/BhWineLaunchHelper.java` | `BhWineLaunchHelper` | New class | Common Wine launch entry point; applies game-specific settings (component versions, environment, HUD prefs) before wine execution. |

#### 10.4 Store-Specific Launchers

| File | Target Class | Injection | What It Does |
|------|--------------|-----------|--------------|
| `extension/GogLaunchHelper.java` | `GogLaunchHelper` | New class | GOG game launch: resolves game_id → exe path, applies Wine settings, launches via WineActivity. |
| (Epic) | No separate class needed | Inline logic | Epic games launch via pending_epic_exe flag set by EpicGamesActivity. |
| (Amazon) | No separate class needed | Inline logic | Amazon games launch via pending_amazon_exe flag set by AmazonGamesActivity. |

---

### 11. RESOURCE OVERLAYS

**Feature:** UI layouts, drawables, and strings for new components.

#### 11.1 Layouts

| File | Purpose |
|------|---------|
| `patches/res/layout/control_element_settings.xml` | RTS control settings layout. |
| `patches/res/layout/llauncher_activity_new_launcher_main.xml` | Main launcher activity overlay. |
| `patches/res/layout/rts_action_picker_dialog.xml` | RTS gesture action selector dialog. |
| `patches/res/layout/rts_action_picker_item.xml` | Single action picker item (radio button). |
| `patches/res/layout/rts_gesture_config_dialog.xml` | Main RTS gesture config dialog. |
| `patches/res/layout/winemu_activitiy_settings_layout.xml` | Wine activity settings panel. |
| `patches/res/layout/winemu_sidebar_controls_fragment.xml` | Sidebar controls fragment (tabs, buttons). |
| `patches/res/layout/winemu_sidebar_hub_type_fragment.xml` | HUD style selector fragment. |

#### 11.2 Drawables

| File | Purpose |
|------|---------|
| `patches/res/drawable/rts_checkbox_button.xml` | RTS checkbox drawable. |
| `patches/res/drawable/rts_checkbox_checked.xml` | Checked checkbox state. |
| `patches/res/drawable/rts_checkbox_unchecked.xml` | Unchecked checkbox state. |
| `patches/res/drawable/rts_dialog_background.xml` | Dialog background rounded rect. |
| `patches/res/drawable/sidebar_taskmanager.xml` | Task manager icon. |

#### 11.3 Values (Colors, Strings, Styles, IDs)

| File | Purpose |
|------|---------|
| `patches/res/values/ids.xml` | New view IDs for component manager, RTS controls, HUD, etc. |
| `patches/res/values/public.xml` | Public resource declarations. |
| `patches/res/values/strings.xml` | UI strings for all features (English). |
| `patches/res/values-ja/strings.xml` | Japanese localization. |
| `patches/res/values/styles.xml` | Text styles, button styles, dialog themes. |
| `patches/res/color/rts_checkbox_tint.xml` | Checkbox color state list. |

---

### 12. ACTIVITY DECLARATIONS (AndroidManifest.xml)

All extension activities are declared in `patches/AndroidManifest.xml`:

#### Store Entry Points
- `app.revanced.extension.gamehub.GogMainActivity` — GOG store view (ID=10 in menu)
- `app.revanced.extension.gamehub.EpicMainActivity` — Epic store view (ID=12)
- `app.revanced.extension.gamehub.AmazonMainActivity` — Amazon store view (ID=11)

#### Component Manager
- `com.xj.landscape.launcher.ui.menu.ComponentManagerActivity` — Component browser/injector
- `com.xj.landscape.launcher.ui.menu.ComponentDownloadActivity` — Component downloader

#### Other Activities
- `app.revanced.extension.gamehub.GogLoginActivity`, `GogGamesActivity`, `GogGameDetailActivity`
- `app.revanced.extension.gamehub.EpicLoginActivity`, `EpicGamesActivity`, `EpicGameDetailActivity`, `EpicFreeGamesActivity`
- `app.revanced.extension.gamehub.AmazonLoginActivity`, `AmazonGamesActivity`, `AmazonGameDetailActivity`
- `app.revanced.extension.gamehub.BhGameConfigsActivity` — Settings export UI
- `app.revanced.extension.gamehub.FolderPickerActivity` — File picker for game paths

#### File Provider
- `app.revanced.extension.gamehub.filemanager.MTDataFilesProvider` — Content provider for file access
- `app.revanced.extension.gamehub.filemanager.MTDataFilesWakeUpActivity` — Wake-up trigger

---

## Injection Pattern Summary

### By Type

| Injection Type | Count | Purpose |
|---|---|---|
| **New Smali Classes** | 80+ | Core functionality (component manager, HUD, sidebar, store integrations) |
| **Smali Patches** | 15 | Hooks into existing GameHub classes (menu, settings, launcher, wine) |
| **New Java Classes** | 50+ | Store backends (GOG, Epic, Amazon), HUD overlays, utilities |
| **Resource Overlays** | 40+ | Layouts, drawables, strings, styles |
| **Manifest Entries** | 25+ | Activities for stores, components, settings |

### By Dex Class Zone

- **smali_classes2:** Settings dialogs (1 patch)
- **smali_classes3:** Game settings view model (1 patch); fetchList callback injection
- **smali_classes4:** PC game settings ops (1 patch)
- **smali_classes5:** Menu & launcher dialogs (1 patch); HomeLeftMenuDialog injection
- **smali_classes6:** Prefs wrapper (1 new)
- **smali_classes9:** Resource ID generators (1 patch)
- **smali_classes10:** Launch strategies (1 patch); settings holder (1 patch)
- **smali_classes11:** Main launcher (1 large patch); BCI launcher (1 new)
- **smali_classes14:** Sidebar fragments (1 patch)
- **smali_classes15:** Wine core (2 patches); X11Controller (1 patch)
- **smali:** Flat patches (2 new: export/import lambdas)
- **smali_classes16:** BannerHub extensions (80+ classes) — near 65k dex limit

---

## Key Integration Points

### 1. Side Menu System
**Root:** `HomeLeftMenuDialog.smali` → Click handler routes to:
- ID=9 → ComponentManagerActivity
- ID=10 → GogMainActivity
- ID=11 → AmazonMainActivity
- ID=12 → EpicMainActivity
- (original GameHub IDs 0–8 for Settings, Cloud, Social, etc.)

### 2. Game Launch Flow
**Root:** `LandscapeLauncherMainActivity.onResume()` checks:
```
if pending_gog_exe → GogLaunchHelper.launch()
if pending_epic_exe → EpicMainActivity (pending flag) → launch
if pending_amazon_exe → AmazonMainActivity (pending flag) → launch
else → original GameHub behavior
```

### 3. Component Availability
**Root:** Game settings UI fetches component list → calls `GameSettingViewModel$fetchList$1.setData()`
→ **INJECTION** → `ComponentInjectorHelper.appendLocalComponents(list, contentType)` appends locally-installed
→ UI shows local + server components in dropdown

### 4. HUD Injection
**Root:** `WineActivity.onResume()` → calls `BhHudInjector.injectOrUpdate()`
→ Checks prefs (winlator_hud, hud_extra_detail, hud_konkr_style)
→ Creates/shows BhFrameRating / BhDetailedHud / BhKonkrHud

### 5. Sidebar Extension
**Root:** `SidebarControlsFragment` added new tabs:
- Task Manager (file browser + process killer)
- Gesture Config (RTS controls setup)
- Performance (CPU/GPU settings)

---

## Permissions Added (AndroidManifest.xml)

```xml
<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE"/>
<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE"/>
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE"/>
<uses-permission android:name="android.permission.QUERY_ALL_PACKAGES"/>
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
<uses-permission android:name="android.permission.CAMERA"/>
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION"/>
<uses-permission android:name="android.permission.BLUETOOTH_*"/>
<!-- ...and many more for device features, sensors, etc. -->
```

---

## Data Flow Examples

### Component Download & Injection
```
ComponentDownloadActivity
  → GitHub Releases API (fetch repos)
  → ComponentDownloadActivity$1..9 (parse JSON, UI updates)
  → Download to cache
  → ComponentInjectorHelper.injectComponent()
    → Detect format (ZIP/WCP)
    → Extract tar (openTar, extractWcp)
    → Parse profile.json/meta.json
    → registerComponent() → EmuComponents.D()
  → GameSettingViewModel sees new component (via appendLocalComponents)
  → User selects in game settings
```

### GOG Game Launch
```
GogMainActivity
  → GogGamesActivity (fetch library via GogApiClient)
  → GogGameDetailActivity (show game, tap Launch)
  → Set pending_gog_exe in prefs
  → Finish activity
  → LandscapeLauncherMainActivity.onResume() detects pending_gog_exe
  → GogLaunchHelper.launch()
    → GogApiClient.getGameExePath()
    → BhWineLaunchHelper.applySettings()
    → Start WineActivity with game exe
```

### HUD Toggle
```
Sidebar button toggles winlator_hud pref
  → WineActivity.onResume() calls BhHudInjector.injectOrUpdate()
  → Reads prefs; destroys old HUD
  → Creates new BhFrameRating/BhDetailedHud/BhKonkrHud
  → Adds to DecorView
  → Refreshes every frame (FPS counter updates)
```

---

## Build Configuration

**Base APK:** GameHub 5.3.5 (ReVanced, gamehub.lite)  
**Min API:** Android 6.0 (API 23)  
**Target API:** Android 14 (API 34)  
**Dex Limit:** smali_classes16 is at/near 65k dex index — no new smali can be added without new dex split.  
**Signing:** AOSP test keys (testkey.pk8, testkey.x509.pem)

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| New smali files (component manager, HUD, sidebar) | 80+ |
| Modified smali files (menu, settings, launcher, wine) | 15 |
| New Java extension classes (stores, utilities) | 50+ |
| Layout/drawable/string resources | 40+ |
| Manifest activity declarations | 25+ |
| Total injection points | 150+ |

**Total lines of code injected:** ~50,000+ (smali + Java)

---

**Document Version:** 1.0  
**Generated:** 2026-04-23  
**Target:** BannerHub repository @ /data/data/com.termux/files/home/BannerHub

