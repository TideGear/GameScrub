# GameHub 6.0 Architecture Reference
**Prepared for BannerHub development — 2026-04-23**

---

## STATUS SUMMARY: Does GameHub 6.0 (KMP/Compose) Exist Yet?

**Short answer: No confirmed public release or source as of April 2026.**

What is confirmed:
- GameSir/GameHub developers acknowledged (February 2026, theMemoryCore interview) that "a very big version upgrade" is in progress but was delayed when resources shifted to another undisclosed GameSir project.
- GameSir Labs maintains active public repos (github.com/gamesir-labs) covering Wine patches, DXVK, DXMT (Metal/macOS), and a Mac issue tracker — none of which have surfaced a KMP Android codebase.
- No public branch, PR, or release exists under any GameHub-affiliated GitHub org that uses KMP or Compose Multiplatform for the Android Wine launcher.
- The hypothesis that "6.0 = KMP rewrite" has not been confirmed by any public statement from GameSir.

**What this document covers:**
1. The concrete, verified architecture of GameHub 5.x (derived from BannerHub smali analysis).
2. What a KMP/Compose Multiplatform rewrite of GameHub *would* look like structurally.
3. How smali patching mechanics change when targeting a KMP app versus a traditional Java/Kotlin Android app.

---

## PART 1 — GameHub 5.x: Verified Architecture

### 1.1 App Identity & Package

| Item | Value |
|------|-------|
| Primary package | `com.xiaoji.egggame` (Play Store ID) / internally `gamehub.org` |
| Patched package (Lite) | `gamehub.lite` |
| Decompiled size | ~1.0 GB uncompressed smali |
| DEX count | 16+ (`classes.dex` through `classes16.dex`) — confirmed by `smali_classes` through `smali_classes16` directories in BannerHub |
| Root package prefix | `com.xj.*` |

### 1.2 Top-Level Smali Namespace Map

All classes live under two primary roots:

```
com.xj.landscape.*     — Launcher / front-end / game library UI
com.xj.winemu.*        — Wine emulator engine / session management
com.xj.pcvirtualbtn.*  — Virtual button / input overlay
com.winemu.core.*      — Low-level Wine/input controller layer
app.revanced.*         — ReVanced extension stubs (in patched builds)
```

SDK garbage that is removed by patches:
```
com.google.firebase.*      — smali_classes3 (~800 files)
com.umeng.*                — smali_classes4 (analytics)
cn.jpush.*, cn.jiguang.*   — smali_classes2/6 (push/tracking)
com.tencent.*              — WeChat/QQ social login
com.alipay.sdk.*           — Payment SDK
```

### 1.3 Launcher / Game Library Module (`com.xj.landscape.launcher`)

Key subpackages:
```
com.xj.landscape.launcher.ui.main.*          — Main activity, launcher entry point
com.xj.landscape.launcher.ui.gamedetail.*    — Game detail screen
com.xj.landscape.launcher.ui.menu.*          — Left nav, home menu dialogs
com.xj.landscape.launcher.ui.setting.*       — Settings holders/fragments
com.xj.landscape.launcher.launcher.strategy.*— Launch strategy implementations
```

**Key classes confirmed from smali:**
- `LandscapeLauncherMainActivity` — top-level launcher Activity (smali_classes11)
- `SteamGameByPcEmuLaunchStrategy` — coroutine-based (`SuspendLambda`) launch orchestrator for Steam games; checks login state via `ISteamService`, validates network, calls `LauncherConfig.d()` callbacks
- `HomeLeftMenuDialog` — left-side navigation drawer (smali_classes5)
- `GameDetailActivity` — game info screen (has `NumberFormatException` guard in patched builds)
- `BhExportLambda` / `BhImportLambda` — BannerHub-injected game config export/import

**Virtual containers:**
Game sessions create and clean up `virtual_containers/{gameId}/` directories. Orphaned containers are purged on uninstall.

### 1.4 Wine Engine Module (`com.xj.winemu`)

```
com.xj.winemu.WineActivity           — Main Wine session Activity (smali_classes15)
com.xj.winemu.sidebar.*              — Sidebar overlay fragments/views (smali_classes3, 14, 16)
com.xj.winemu.settings.*             — In-session settings (smali_classes2, 3, 4)
com.xj.winemu.view.*                 — Touch overlay views (smali_classes16)
com.winemu.core.controller.*         — Low-level input/environment (smali_classes6, 15)
```

**WineActivity (`com.xj.winemu.WineActivity`):**
- Extends `FocusableAppCompatActivity`
- Implements `GamepadEventListener`, `IGamePadManagerOwner`
- Owns: `WinUIBridge`, `GamepadManager`, `VirtualGamepadController`, `WineInGameSettings`
- Has graphics effect fields: HDR, CAS (contrast-adaptive sharpening), CRT
- Owns `InputControlsManager` and `InputControlsView` for virtual controls
- Wine window lifecycle events handled via callback: `app_launch`, `sync_apps_complete` states
- Does NOT directly exec Wine binary — bridges through `WinUIBridge` to native layer

**WineActivityDrawerContent:**
- Extends `FocusableConstraintLayout`
- Uses `WinemuActivitiySettingsLayoutBinding` (XML view binding — confirms 5.x is NOT Compose)
- Lazy-loads fragments via `FragmentManager` into a Map cache:
  - `"SidebarControlsFragment"`
  - `"SidebarPerformanceFragment"`
  - `"SidebarSettingsFragmentKey"`
  - `"BhTaskManagerFragment"` (injected by BannerHub)

**Wine binary path (from GameHub Lite analysis):**
```
/data/data/gamehub.lite/files/wine/bin/wine
```
Access is gated by SELinux — stock devices require permissive policy or Magisk.

### 1.5 Settings Module (`com.xj.winemu.settings`)

- `GameSettingViewModel` — ViewModel for per-game settings, uses coroutines (`fetchList$1`, `fetchList$2`)
- `PcGameSettingOperations` — operations class for applying settings to a container
- `SelectAndSingleInputDialog` — UI dialog with `Companion` object (Kotlin companion pattern)
- `CpuMultiSelectHelper` — CPU affinity selection (BannerHub-injected, smali_classes16)

### 1.6 UI Technology in 5.x

GameHub 5.x uses **XML layouts + View Binding + Fragments**, NOT Compose.

Evidence:
- `WinemuActivitiySettingsLayoutBinding` — generated View Binding class
- Fragment-based sidebar architecture with explicit `FragmentManager`
- `ConstraintLayout` subclass for sidebar host view
- RecyclerView adapters (e.g., `BhComponentAdapter$ViewHolder`)
- Menu dialogs via `HomeLeftMenuDialog`

This is conventional pre-Compose Android architecture: Activities own Fragments, Fragments bind XML layouts, ViewModels expose LiveData/Flow.

### 1.7 BannerHub's Injection Layer (smali_classes16)

All BannerHub new code lives in `smali_classes16` to avoid DEX method index overflow. Key injected classes:

```
com.xj.winemu.sidebar.BhHudInjector          — HUD overlay injection point
com.xj.winemu.sidebar.BhTaskManagerFragment  — Wine process task manager tab
com.xj.winemu.sidebar.BhPerfSetupDelegate    — Performance settings delegate
com.xj.winemu.sidebar.BhRootGrantHelper      — Root permission helper
com.xj.winemu.sidebar.BhInitLaunchRunnable   — Launch-phase hook
com.xj.landscape.launcher.ui.menu.ComponentManagerActivity  — Component manager UI
com.xj.landscape.launcher.ui.menu.ComponentDownloadActivity — Component downloader
com.xj.landscape.launcher.ui.menu.WcpExtractor              — WCP/ZIP component extractor
com.xj.winemu.settings.CpuMultiSelectHelper                  — CPU selection
```

**Note:** `smali_classes12` is at the DEX method index limit and is never reassembled — the original `classes12.dex` is extracted from the base APK and injected post-rebuild. This is a critical constraint for any future patching work.

---

## PART 2 — What a GameHub 6.0 KMP/Compose Rewrite Would Look Like

This section is architectural analysis, not confirmed fact. It describes what "6.0 built on KMP + Compose Multiplatform" means in practice.

### 2.1 KMP Source Set Structure vs Traditional Android

**Traditional (what GameHub 5.x is):**
```
app/src/main/java/com/xj/...   — All Kotlin/Java source
app/src/main/res/layout/...    — XML layouts
```

**KMP project:**
```
shared/src/commonMain/kotlin/  — 70-90% of codebase
    domain/model/
    domain/usecase/
    data/repository/
    presentation/viewmodel/     (if using shared VMs)

shared/src/androidMain/kotlin/ — Android-specific actuals
    platform/AndroidLogger.kt  (actual fun log())
    platform/AndroidFileSystem.kt

androidApp/src/main/...        — Android UI layer only
    MainActivity.kt
    compose screens/
```

For a Wine-based app, the shared module would contain:
- Game library data models, repository interfaces
- Launch strategy logic (the `SteamGameByPcEmuLaunchStrategy` equivalent)
- Settings data classes and persistence logic
- API client (game metadata, component downloads)

Platform-specific (`androidMain`) would contain:
- Wine process management (Android-only via JNI/exec)
- File provider implementations
- Android Activity lifecycle hooks
- GPU driver injection (AdrenoTools, Mali driver loading)

### 2.2 expect/actual: What It Looks Like in DEX

The `expect/actual` mechanism is a **compile-time construct only**. In the final APK:

- There is no `expect` keyword or annotation in DEX
- The `actual` implementation is compiled as a plain class, indistinguishable from any other Kotlin class
- The class name is whatever you named it — no KMP-specific suffix or prefix
- At DEX level, a KMP `actual class PlatformLogger` in `androidMain` becomes `Lcom/xj/platform/PlatformLogger;` — identical to a non-KMP class

**Implication for patching:** You cannot identify KMP-origin classes from smali alone. You need the source structure or Kotlin metadata annotations (`@Metadata`) to trace which classes came from `commonMain` vs `androidMain`.

### 2.3 DEX Layout of a KMP App

A KMP Android APK compiled with D8/R8 produces the same multidex structure as any large Kotlin app:

```
classes.dex        — boot classes (Application, main Activity, startup-critical code)
classes2.dex       — large library code (likely org.jetbrains.* runtime)
classes3.dex       — more library/SDK code
...
classesN.dex       — app feature code
```

**New packages you will see in a Compose Multiplatform APK that do NOT exist in GameHub 5.x:**

```
androidx.compose.runtime.*           — Compose runtime (recomposition engine)
androidx.compose.ui.*                — Layout system
androidx.compose.foundation.*        — Foundation components
androidx.compose.material3.*         — Material 3 components
org.jetbrains.compose.*              — CMP-specific extensions (if CMP, not just Jetpack Compose)
kotlin.coroutines.*                  — Coroutine runtime (already present in 5.x)
```

**On Android, Compose Multiplatform uses the exact same Jetpack Compose artifacts that Google publishes.** CMP does NOT use a separate Skia renderer on Android — it uses the standard Compose/HWUI pipeline. The Skia/Skiko overhead only appears for iOS/Desktop targets.

This means: a GameHub 6.0 Android APK built with CMP will have the same Compose DEX packages as a standard Jetpack Compose app. No exotic `skiko` JNI libraries in the Android APK.

### 2.4 Compose UI vs XML: What Changes for Patchers

**5.x (XML + Views):**
- UI is in `res/layout/*.xml` — editable via apktool resource overlay
- `R.id.*` constants map to view IDs — patchable in `R$id.smali`
- Fragment classes are explicit Java/Kotlin classes with lifecycle methods — easy injection targets
- View Binding classes (`*Binding.smali`) are generated, but the binding inflation call in a fragment is a clear hook point

**6.0 (Compose):**
- No XML layout files — zero items in `res/layout/`
- UI is entirely defined as Kotlin `@Composable` functions compiled to bytecode
- The Compose compiler transforms `@Composable` functions: it inserts `Composer` and `changed` parameters, adds recomposition skip logic, and generates `ComposableSingletons` inner classes
- `R.id` does not exist for Compose — semantic testing uses string keys, not integer IDs
- Fragment concept is largely gone — navigation is handled by `NavController` and `NavHost` composables

**What replaces Fragment injection points:**

In 5.x, BannerHub injects by patching fragment constructors or lifecycle methods. In a Compose app:
- The equivalent hook is the ViewModel (still a plain class, patchable normally)
- Navigation routes (string constants or sealed classes) determine which screen loads
- `CompositionLocal` providers are set up in the root composable — modifying these is the Compose equivalent of modifying `Application.onCreate()`

**The @Composable function smali signature:**
A function like `fun GameListScreen(viewModel: GameListViewModel)` becomes in smali:
```smali
.method public static GameListScreen(Lcom/xj/ui/GameListViewModel;Landroidx/compose/runtime/Composer;I)V
```
The last two params (`Composer`, `Int`) are injected by the Compose compiler plugin. Every composable has them. This is how you identify composable functions in smali: they take `Landroidx/compose/runtime/Composer;I` at the end.

### 2.5 Where Patch Injection Points Live in a KMP App

| 5.x Target | 6.0 KMP Equivalent | Notes |
|------------|-------------------|-------|
| `WineActivity` fields | Same class, same pattern | Activity is still Android-specific, likely in `androidMain` |
| `SteamGameByPcEmuLaunchStrategy` | SharedModule `UseCase` class | May be in `commonMain`, compiled to normal DEX |
| Fragment lifecycle methods | ViewModel methods or `LaunchedEffect` hooks | ViewModel is easier to patch; LaunchedEffect lives inside composable |
| `HomeLeftMenuDialog` XML layout | Composable function arguments / slot lambdas | No XML to overlay; must patch the composable call site |
| `WinemuActivitiySettingsLayoutBinding` | No equivalent | View Binding is gone; replaced by composable state |
| `Application.onCreate()` | Same — still present | Reliable injection point across all Android app types |
| `R$id.smali` constants | Not applicable | Compose does not use integer view IDs |

**Most stable injection points in a KMP/Compose app:**
1. `Application.onCreate()` — still first-run code, exists in all Android apps
2. ViewModel constructors and public methods — compiled to plain classes, no Compose magic
3. Repository/UseCase classes from `commonMain` — plain Kotlin, fully patchable
4. `MainActivity` or root Activity — entry to the Compose host, pre-compose hook
5. Navigation route constants — if string literals, patchable; if sealed class, class replacement needed

### 2.6 R8/ProGuard Obfuscation in a KMP App

A production KMP APK will almost certainly be R8-minified. What this means:

- Class names become `a.b.c.d`, `a.b.c.e`, etc.
- Method names become `a()`, `b()`, `c()`
- The Kotlin `@Metadata` annotation is usually **preserved by default** — this is your lifeline for reverse engineering KMP apps; it contains the original class/function names in encoded form
- JADX and Kotlin Metadata Printer can decode `@Metadata` to recover original names
- BannerHub currently patches unobfuscated builds (GameHub 5.x ReVanced is not R8-obfuscated post-patch). If 6.0 ships with R8, all existing patch fingerprints break.

**Strategy for obfuscated KMP apps:**
- Use JADX with Kotlin metadata support to recover class map
- Fingerprint by method signature + instruction patterns, not by class name
- Watch for `ComposableSingletons$FileNameKt` classes — Compose compiler generates these predictably even after obfuscation
- ViewModel classes often retain meaningful names if the app uses `@HiltViewModel` or similar reflection-dependent DI

### 2.7 JNI / Native Layer

GameHub's Wine, Box64, FEX, and DXVK are all native binaries in `lib/arm64-v8a/`. This does NOT change in a KMP rewrite:

- KMP affects the Kotlin/JVM layer only
- `lib/arm64-v8a/*.so` files are loaded via `System.loadLibrary()` — this call site is in `androidMain` or the `Application` class
- Patching the JNI bridge classes (any class that calls `native` methods) remains the same technique regardless of KMP

gamesir-labs maintains:
- `gamesir-labs/wine` — their Wine fork (C, updated April 2026)
- `gamesir-labs/dxvk` — Vulkan D3D11 (updated April 2026)
- `gamesir-labs/dxmt` — Metal D3D11 for macOS (updated April 2026)
- `gamesir-labs/rosettax87_jit` — x87 JIT (updated April 2026)

These will remain native `.so` files. The KMP rewrite only affects the Java-visible launcher/UI layer.

---

## PART 3 — Practical Smali Patching Checklist for KMP Apps

Before targeting a KMP/Compose APK for the first time:

**Reconnaissance:**
- [ ] Decompile with `apktool d` — check if `res/layout/` is empty (confirms Compose)
- [ ] Check `smali*/androidx/compose/` — presence confirms Compose usage
- [ ] Check `smali*/org/jetbrains/compose/` — presence means Compose Multiplatform (not just Jetpack Compose)
- [ ] Dump Kotlin metadata from `Application` class using `kotlinx-metadata-jvm` to recover original names if R8-obfuscated
- [ ] Identify the root `@Composable` in `MainActivity` — usually `setContent { AppTheme { NavHost(...) } }`

**DEX budget planning:**
- [ ] Count existing `smali_classesN` directories — KMP apps are large (Compose runtime alone = ~15k methods)
- [ ] Expect 10-20 DEX files in a production KMP app with Compose
- [ ] New injection classes still go in the highest-numbered available DEX
- [ ] Check if `classes.dex` (smali/) is at the 64K method limit before touching it

**Injection strategy:**
- [ ] Prefer ViewModel/UseCase injection over composable injection — they are stable, testable, plain Kotlin
- [ ] If you must hook UI logic: patch the ViewModel the composable observes, not the composable itself
- [ ] `Application.onCreate()` is always safe for one-time hooks
- [ ] Avoid patching Compose-generated inner classes (`ComposableSingletons$*`, `*$Companion`) — unstable across versions
- [ ] For navigation gating (e.g., unlock a screen): patch the route guard in NavGraph setup or the ViewModel check, not the composable

**Rebase risk:**
- [ ] KMP apps that use `expect/actual` — the `actual` class in `androidMain` is your target, not the `expect` declaration (which doesn't exist in DEX)
- [ ] Shared module classes from `commonMain` compile identically to `androidMain` classes in DEX — no way to distinguish them structurally; rely on package naming conventions (`*.common.*` vs `*.android.*`)
- [ ] Compose compiler transforms composable functions — function signatures change when compiler version changes; fingerprint methods by their non-Compose parameters only

---

## PART 4 — GameSir / GameHub Org Reference

| Repo | Purpose | Language | Last Updated |
|------|---------|----------|-------------|
| gamesir-labs/wine | Wine fork for GameHub/GameFusion | C | 2026-04-21 |
| gamesir-labs/dxvk | Vulkan D3D11 for Linux/Wine | C++ | 2026-04-23 |
| gamesir-labs/dxmt | Metal D3D11 for macOS/Wine | C++ | 2026-04-23 |
| gamesir-labs/rosettax87_jit | x87 JIT for Rosetta | C | 2026-04-23 |
| gamesir-labs/gamehub-for-mac | Issue tracker for Mac client | (issue tracker) | 2026-04-23 |

No Android KMP source is public. The "very big version upgrade" (Feb 2026 announcement) remains unreleased.

---

## Key Conclusions

1. **GameHub 6.0 with KMP is not publicly confirmed or released.** The developer cited a delay due to resource reallocation. There is no public branch, repo, or source to target.

2. **GameHub 5.x uses traditional XML + View Binding + Fragments** — the architecture BannerHub already patches. This will continue to be the baseline until 6.0 ships.

3. **When 6.0 arrives as a KMP/Compose app**, the primary changes for patching are:
   - No XML layouts to overlay; UI is bytecode
   - Composable functions have injected `Composer, Int` parameters
   - ViewModel classes remain the best injection target
   - DEX count will be higher but the injection technique (highest available DEX file) is unchanged
   - expect/actual leaves no trace in DEX; patch the `actual` implementation class

4. **The native Wine/DXVK/Box64 layer is unaffected by a KMP rewrite.** `.so` patching and `loadLibrary` hook techniques remain identical.

5. **The most dangerous change for BannerHub** would be if 6.0 ships with R8 obfuscation enabled. Current BannerHub patches rely on stable, unobfuscated class names. Obfuscation would require a complete fingerprint-based rewrite of the patch pipeline.
