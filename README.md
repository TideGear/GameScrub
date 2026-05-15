# GameHub Vibration Fix

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, libevshim guest-side SDL
> keepalive, and the entire vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> of just the vibration mod, supporting stock 6.0.2 and 6.0.4 base APKs.

A minimal patch on top of stock GameHub (6.0.2 or 6.0.4) that adds
**PC-accurate XInput rumble support** for Wine games. Nothing else is
changed. This is for the sake of having the working achievements of
stock GameHub plus fixed vibration.

What you get over stock GameHub:

- **Dual-motor low/high dispatch.** Wine games calling `XInputSetState(slot,
  low, high)` get the two motors driven independently via Android
  `CombinedVibration.startParallel` on ≥ 2-motor controllers. Stock GameHub
  blends both motors into a single haptic pulse; this preserves the heavy
  / light distinction the way the game intended.
- **Sustained rumble holds past 1 s.** SDL2's internal 1 s
  `rumble_expiration` auto-stops sustained rumble on stock; an LD_PRELOAD
  shim (`libevshim.so`) re-issues `SDL_JoystickRumble` every 500 ms with a
  2 s duration so the timer never fires.
- **Experimental preload-free Wine patch.** For games that fail when
  `libevshim.so` is mapped, the APK's launch-time Java hook patches the
  app-owned `aarch64-unix/winebus.so` directly. The offline helper
  [scripts/patch_winebus_rumble_duration.py](scripts/patch_winebus_rumble_duration.py)
  applies the same patch to extracted components. It changes only the two
  nonzero SDL rumble start calls to pass `0xffffffff` as the SDL duration;
  zero-duration stop calls still stop immediately.
- **Instant release** when the game stops rumble — no phantom-suppression
  timer extending the motor past the actual stop call.

### Per-game "Engine keepalive" toggle

A small set of games silently exit at launch when `libevshim.so` is mapped
into their Wine subprocess address space — verified to be pure mmap
presence rather than symbol exports or constructor side effects. Wine's
preloader is famously fussy about address-space layout; whatever it does
for these specific games conflicts with our extra mapping. The first
confirmed case is **Shotgun King: The Final Checkmate** (GameMaker Studio
2), which exits ~700 ms after `boot job completed` with `normalExit=true`
and no tombstone.

The PC Vibration Settings dialog (long-press a game → settings → PC
Vibration) has an **"Engine keepalive"** checkbox that defaults checked.
Uncheck it for any game that fails to launch — the smali envbuilder
patch ([scripts/apply_vibration_patches.py](scripts/apply_vibration_patches.py))
calls
[BhVibrationController.shouldPreloadEvshim()](extension/BhVibrationController.java)
before adding libevshim to LD_PRELOAD; if the per-game pref
(`bh_evshim_enabled` under `pc_g_setting<gameId>`) is false, the prepend
is skipped, libevshim never enters that launch's LD_PRELOAD, and the
dynamic linker never maps it into the Wine subprocess. Tradeoff for the
disabled game: SDL's 1 s rumble auto-expiry kicks back in, so sustained
rumble cuts at one second. Dual-motor dispatch and instant release still
work (smali patches 1–3 are independent of libevshim).

The APK attempts the Wine-side `winebus.so` duration patch once per app
process before deciding whether to add `libevshim.so` to LD_PRELOAD. For
Shotgun King, disable **Engine keepalive**. That avoids the `libevshim.so`
mapping that breaks launch, while the Wine-side duration patch keeps SDL
from auto-stopping rumble at one second.

The toggle's setting lives under the same `pc_g_setting<gameId>` file as
Mode/Intensity, so it round-trips through Export/Import the same way.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
(pick base version 6.0.2 / 6.0.4) or push of a `v*-6.0.2*` / `v*-6.0.4*`
tag.

One-time setup per base version: upload the original GameHub APK as an
asset on a release tagged `base-apk-<version>` in this repo (e.g.
`base-apk-6.0.4` for `GameHub_6.0.4_fadf3b5c43f0a3900027758d372b3d54.apk`).
The workflow `gh release download`s the matching base for the version it
was triggered against.

`scripts/apply_vibration_patches.py` auto-detects the base version from
the smali layout of the decompiled tree:

- **6.0.2** uses ProGuard names `za8` (Physical), `dg5` (env builder),
  `ns2.I0` (joinToString helper).
- **6.0.4** renames those to `ab8`, `bg5`, `ps2.I0` respectively.

Full rename map and per-version anchor set are at the top of the script.

The pipeline:

1. `apktool d` the base APK
2. Strip `android:usesPermissionFlags` and
   `android:enableOnBackInvokedCallback` from the manifest (apktool 2.9.3's
   bundled aapt2 doesn't know them; cosmetic, harmless)
3. `python3 scripts/apply_vibration_patches.py` — four smali hooks
4. (optional) `python3 scripts/apply_login_bypass.py` — patch the
   auth-state combiner + privacy-popup gate
5. `cmake/ninja` build of `native/evshim/libevshim.so` for arm64-v8a
6. `apktool b`
7. `javac + d8` of the two `extension/Bh*.java` files → next free
   `classesN.dex` slot (classes7), inject into the APK
8. `zipalign + apksigner` with `testkey.pk8` / `testkey.x509.pem`
9. Upload as `GameHub-Vibration-Fix-<version>.apk`

## Project layout

```
extension/
  BhVibrationController.java       singleton dispatcher (smali entry points,
                                   per-game settings, keepalive thread)
  BhVibrationSettingsActivity.java Mode/Intensity dialog UI

native/evshim/
  evshim.c, CMakeLists.txt         guest-side LD_PRELOAD shim. Patches
                                   winebus.so's pSDL_JoystickRumble +
                                   pSDL_JoystickClose .bss pointers so
                                   sustained rumble survives SDL's 1 s
                                   auto-expiry.

scripts/
  apply_vibration_patches.py       smali hooks against a decompiled
                                   apktool tree (6.0.2 or 6.0.4;
                                   version auto-detected from layout).
  patch_winebus_rumble_duration.py experimental preload-free patch for
                                   extracted aarch64-unix/winebus.so.

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone.
