# GameHub Vibration Fix

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, libevshim guest-side SDL
> keepalive, and the entire vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> of just the vibration mod onto a 6.0.x base.

A minimal patch on top of stock GameHub (6.0.1 or 6.0.2) that adds
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
- **Instant release** when the game stops rumble — no phantom-suppression
  timer extending the motor past the actual stop call.

Multi-controller support and the connect-time wake-up that the 5.3.5 mod
needed are dropped in this build — the 6.0.x gamepad subsystem refactor
fixed the lazy-attach issue natively.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
(pick base version 6.0.1 or 6.0.2) or push of a `v*-6.0.1*` / `v*-6.0.2*`
tag.

One-time setup per base version: upload the original GameHub APK as an
asset on a release tagged `base-apk-<version>` in this repo (e.g.
`base-apk-6.0.2` for `GameHub_6.0.2_e404e8687204521e0aa7963bd49a5a6b.apk`).
The workflow `gh release download`s the matching base for the version it
was triggered against.

`scripts/apply_vibration_patches.py` auto-detects the base version from
the obfuscated class names present in the decompiled tree (`g58`/`sc5`
for 6.0.1, `za8`/`dg5` for 6.0.2 — full rename map is at the top of the
script).

The pipeline:

1. `apktool d` the base APK
2. Strip `android:usesPermissionFlags` and
   `android:enableOnBackInvokedCallback` from the manifest (apktool 2.9.3's
   bundled aapt2 doesn't know them; cosmetic, harmless to drop)
3. `python3 scripts/apply_vibration_patches.py` — four smali hooks
4. `cmake/ninja` build of `native/evshim/libevshim.so` for arm64-v8a
5. `apktool b`
6. `javac + d8` of the two `extension/Bh*.java` files → `classes7.dex`,
   inject into the APK
7. `zipalign + apksigner` with `testkey.pk8` / `testkey.x509.pem`
8. Upload as `GameHub-6.0.1-vib.apk`

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
  apply_vibration_patches.py       four smali hooks against a decompiled
                                   apktool tree (6.0.1 or 6.0.2; version
                                   auto-detected from class names).

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone. This fork ships **only the vibration mod**.
