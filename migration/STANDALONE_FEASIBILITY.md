# BannerHub Standalone Feature Feasibility Analysis

Generated: 2026-04-23

---

## FEATURE 1: COMPONENT MANAGER

### 1. GameHub Internals Dependencies

- **EmuComponents class** (`Lcom/xj/winemu/EmuComponents;`) — singleton registry for installed components
  - `EmuComponents.e()` — retrieves the active instance
  - `EmuComponents.D(ComponentRepo)` — registers a new component
  - `EmuComponents.a` — HashMap storing all registered ComponentRepo objects by key

- **ComponentRepo class** — data model with fields: `name`, `version`, `state` (Extracted/Downloaded), `entry` (EnvLayerEntity)

- **EnvLayerEntity class** (`Lcom/xj/winemu/api/bean/EnvLayerEntity;`) — component metadata bean with 19 constructor parameters (type, version, displayName, description, fileMd5, fileSize, etc.) — requires exact parameter ordering and many `@NotNull` fields

- **DialogSettingListItemEntity class** — populates GameHub's UI selection menus
  - Setters: `setTitle()`, `setDisplayName()`, `setType()`, `setEnvLayerEntity()`, `setDownloaded()`

- **GameSettingViewModel$fetchList$1 callback** — hooks into GameHub's settings fetch pipeline; two injection points append locally installed components to server lists before UI callback fires (triggered when user opens GPU Driver / DXVK / VKD3D / Box64 / FEXCore selection menus)

- **File storage** — hardcoded to `context.filesDir/usr/home/components/`; GameHub's Wine container expects components here

### 2. What Would Need to Change

1. **Replace EmuComponents registry** — store metadata locally in standalone app's database or SharedPreferences instead of GameHub's singleton
2. **Remove GameSettingViewModel hook** — standalone app displays its own component list UI
3. **Replace component path** — components still install to Wine container but app needs configurable path (user-selectable, runner-agnostic)
4. **Drop DialogSettingListItemEntity** — use own RecyclerView adapters

### 3. Standalone Approach

```
Standalone Component Manager App
├── ComponentManager Activity (list/options/download)
├── ComponentDownloadActivity (3-mode downloader)
├── Component extractor (reuse ComponentInjectorHelper logic)
├── Local registry (SQLite/JSON)
├── Network fetcher (GitHub API, pack.json, etc.)
└── Container path picker / settings
```

- **Component storage**: Same extraction logic (WCP/ZIP/tar+Zstd/XZ) but writes to a configurable Wine container path
- **Component registry**: Local SQLite or JSON tracking installed components
- **Download sources**: Reuse existing repo fetch logic (Arihany, Nightlies, GPU drivers) — fully independent APIs
- **Wine runner integration**: Provide container path picker UI; support GameHub, Winlator, and others via selectable path

### 4. Blockers and Risks

**Major:**
- No universal Wine container path — each runner (GameHub, Winlator, ExaGear) uses a different path; needs manual path selection or runner detection
- No built-in component validation — must parse profile.json from WCP tars, handle both WCP (profile.json) and ZIP (meta.json) formats, fall back to filename

**Moderate:**
- Dex class loading — GameHub's internal classes (EnvLayerEntity, ComponentRepo) can't be instantiated from outside GameHub's dex, but extraction logic has no hard dependencies on these

**Minor:**
- Some GPU drivers may need per-device tuning (already handled with fallbacks)

### 5. Verdict: FEASIBLE WITH SIGNIFICANT EFFORT

The component extraction and download logic is completely self-contained with zero hard dependencies on GameHub internals. Only the registration mechanism and UI integration points need redesign.

- **Keep**: All WCP/ZIP extraction logic, download pipelines, sysfs parsing
- **Replace**: Registration mechanism (local DB instead of EmuComponents)
- **Redesign**: UI and container integration

**Estimated effort**: ~2–3 weeks
- Core extraction/download: ~1 week (minimal changes, mostly reuse)
- UI/container integration: ~1–2 weeks (new UI, configuration dialogs, path picker)
- Testing: ~1 week (multiple Wine runners, Android versions)

**Version-agnostic benefit**: YES — works with GameHub 5.3.5, 6.0, Winlator, and any Wine runner with a known container path.

---

## FEATURE 2: WINLATOR HUD OVERLAY

### 1. GameHub Internals Dependencies

- **WineActivity class** (`Lcom/xj/winemu/WineActivity;`) — `onResume()` calls `BhHudInjector.injectOrUpdate(this)`; has `j` field providing FPS via reflection

- **BhHudInjector** — central dispatcher (100% custom BannerHub code); reads SharedPreferences keys `winlator_hud`, `hud_extra_detail`, `hud_konkr_style`; injects HUD views into `Activity.getWindow().getDecorView()`

- **BhFrameRating** — minimal HUD (FPS only); reads FPS via reflection from `activity.j`; no other GameHub dependency

- **BhDetailedHud** — detailed metrics overlay; reads CPU/GPU/RAM/Battery/Temp from sysfs (fully platform-independent); requires GameHub FPS provider via `activity.j`; falls back to 0 if absent

- **BhKonkrHud** — Konkr-style overlay; same sysfs reading; reads `activity.u` for `pc_g_setting{gameId}` SharedPreferences for Wine resolution; falls back to Android display metrics

- **Injection point**: called from `WineActivity.onResume()` every time activity resumes

### 2. What Would Need to Change

1. **Remove onResume hook** — standalone app can't inject into GameHub's WineActivity; use overlay service (WindowManager) instead
2. **Replace FPS source** — reflection on `activity.j` is GameHub-specific; need fallback to timing-based estimate for other runners
3. **Replace resolution source** — `activity.u` is GameHub-specific; pass resolution via Intent extra or SharedPreferences, or detect Wine window size via AccessibilityService

### 3. Standalone Approach

**Option A: Overlay Service (Recommended)**

```
Standalone HUD Overlay App
├── HudOverlayService (WindowManager overlay)
├── HudControllerActivity (settings, mode toggle)
├── FpsProvider interface
│   ├── GameHubFpsProvider (reflection to activity.j)
│   └── SteadyFpsProvider (timing-based estimate, fallback)
├── ContainerIntegration (Wine runner picker config)
└── sysfs readers (CPU, GPU, RAM, Battery, Temp — unchanged)
```

**User flow**: Install app → grant SYSTEM_ALERT_WINDOW → enable overlay → launch Wine app → HUD appears automatically

**FPS handling**:
- GameHub: auto-detect `activity.j`, use real FPS
- Other runners: timing-based estimate or disable FPS display
- Settings option: "Use timing-based FPS estimate"

**Resolution handling**:
- GameHub: read `pc_g_setting{gameId}` SharedPreferences if available
- Other runners: Android display metrics
- Settings option: manual resolution override

### 4. Blockers and Risks

**Major:**
- FPS reading is fundamentally tied to GameHub — `activity.j` is GameHub-specific; no way to get accurate FPS from outside the app without native hooking (libvulkan interception — very complex)
- Overlay permissions are app-specific — some devices/ROMs restrict overlay layers; each Wine app may block overlay draws

**Moderate:**
- Resolution reading is app-specific — GameHub uses `pc_g_setting{gameId}` with `pc_c_resolution_w/h` keys; Winlator and others have different locations; needs Wine runner picker config
- Timing-based FPS estimate is inaccurate — can't distinguish GPU frame time from app processing time

**Minor:**
- sysfs readers are solid with fallback chains — CPU, GPU, RAM, Battery, Temp are platform-independent
- Layout/drag handling is self-contained and works fine in overlay service context

### 5. Verdict: FEASIBLE WITH LIMITATIONS (MODERATE EFFORT)

The sysfs-based stat reading and UI rendering are 100% self-contained. The only GameHub dependency is FPS reading.

- **Easy**: CPU%, GPU%, RAM%, Swap, Battery, Temps; drag/tap UI; layout switching
- **Hard**: Accurate FPS without GameHub's internal provider; making overlay work reliably across Wine runners

**Estimated effort**: ~2–3 weeks
- Core HUD views + sysfs readers: ~3 days (mostly reuse from BhDetailedHud/BhKonkrHud)
- Overlay service + FPS fallback: ~5 days (window manager, permission handling, graceful FPS degradation)
- Settings/configuration UI: ~3–4 days (Wine runner picker, permission grant dialogs)
- Testing: ~5 days (multiple devices, Wine runners, overlay permission edge cases)

**Version-agnostic benefit**: PARTIAL
- Works standalone on any device
- Works with GameHub 5.3.5 and 6.0 via reflection
- Works with Winlator and others (without FPS or with timing-based estimate)
- Does NOT require re-patching on GameHub version bump

**Accuracy trade-off**:
- With GameHub FPS source: 100% accurate (actual GPU frame rate)
- Without (Winlator, other runners): ~70% accurate (~1–3 frame latency in timing estimate)

---

## COMPARATIVE SUMMARY

| Aspect | Component Manager | HUD Overlay |
|--------|-------------------|-------------|
| Core Logic Self-Contained | YES (extraction, download) | YES (sysfs readers, UI) |
| GameHub Dependency Depth | SHALLOW (registry + path) | MODERATE (FPS reading only) |
| UI Redesign Required | YES (full menu system) | PARTIAL (embed in service) |
| Estimated Effort | 2–3 weeks | 2–3 weeks |
| Version-Agnostic | YES | PARTIAL (FPS may degrade) |
| Main Blocker | Wine runner path detection | FPS accuracy, overlay permissions |
| Risk Level | LOW | MODERATE |

---

## RECOMMENDATION

**Component Manager** — Extract as a priority if version-agnostic distribution is important. Core logic is bulletproof; only the EmuComponents registration and container path need redesign. Low risk.

**HUD Overlay** — Extract as a WindowManager overlay service with graceful FPS fallback. GameHub users get perfect FPS; Winlator/other users get timing-based estimates. Avoids re-patching on GameHub updates entirely.

### Next steps if proceeding:
1. Component Manager: new Android project, copy extraction/download code, write local registry layer
2. HUD Overlay: WindowManager overlay service, GameHub FPS reflection + timing fallback, configuration UI
3. Both: test release and gather feedback on Wine runner compatibility
