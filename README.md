# GameHub Vibration Fix

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, libevshim guest-side SDL
> keepalive, and the entire vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> of just the vibration mod, supporting stock 5.3.5 and 6.0.2 base APKs.

A minimal patch on top of stock GameHub (5.3.5 or 6.0.2) that
adds **PC-accurate XInput rumble support** for Wine games. Nothing else
is changed. This is for the sake of having the working achievements of
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
- **Multi-controller wake-up (5.3.5 only).** A connect-time hook fires a
  button-14 flicker on each newly-connected slot's `GamepadState` so
  libvfs's lazy `SDL_JOYDEVICEADDED` lands before the user provides input.
  Without it, the second/Nth controller's rumble silently no-ops on 5.3.5
  until you press a button. 6.0.2 doesn't need this — the gamepad-
  subsystem refactor in the 6.0 line fixed lazy-attach natively.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
(pick base version 5.3.5 or 6.0.2) or push of a `v*-5.3.5*` /
`v*-6.0.2*` tag.

One-time setup per base version: upload the original GameHub APK as an
asset on a release tagged `base-apk-<version>` in this repo (e.g.
`base-apk-6.0.2` for `GameHub_6.0.2_e404e8687204521e0aa7963bd49a5a6b.apk`).
The workflow `gh release download`s the matching base for the version it
was triggered against.

`scripts/apply_vibration_patches.py` auto-detects the base version from
the smali layout of the decompiled tree:

- **5.3.5** ships unobfuscated symbols — anchors live under
  `smali_classes7/com/winemu/core/{controller,gamepad}/`.
- **6.0.2** uses ProGuard names `za8` (Physical), `dg5` (env builder),
  `ns2.I0` (joinToString helper).

Full rename map and per-version anchor set are at the top of the script.

The pipeline:

1. `apktool d` the base APK
2. Strip `android:usesPermissionFlags` and
   `android:enableOnBackInvokedCallback` from the manifest (apktool 2.9.3's
   bundled aapt2 doesn't know them; cosmetic, harmless on 6.0.2 — no-op
   on 5.3.5 where these attributes don't exist)
3. `python3 scripts/apply_vibration_patches.py` — four smali hooks on
   6.0.2, five on 5.3.5 (extra connect-time wake-up)
4. (optional 6.0.2 only) `python3 scripts/apply_login_bypass.py` — patch
   the auth-state combiner + privacy-popup gate
5. (5.3.5 only) rename package to `gamehub.v535` so it coexists with
   the canonical 6.0.2 install — direct manifest edit, no apktool
   `renameManifestPackage` (mirrors BannerHub's `gamehub.lite` recipe)
6. `cmake/ninja` build of `native/evshim/libevshim.so` for arm64-v8a
7. `apktool b`
8. `javac + d8` of the two `extension/Bh*.java` files → next free
   `classesN.dex` slot (classes7 on 6.0.2, classes12 on 5.3.5), inject
   into the APK
9. `zipalign + apksigner` with `testkey.pk8` / `testkey.x509.pem`
10. Upload as `GameHub-Vibration-Fix-<version>.apk`

### Side-by-side install

5.3.5 and 6.0.2 both ship as `package com.xiaoji.egggame` upstream, so
only one can be installed at a time without intervention. The CI
treats 6.0.2 as the canonical install (keeps the original package
name) and always renames the 5.3.5 build to `package gamehub.v535`,
with all FileProvider authorities and custom permission names
rewritten under the new prefix and the launcher label suffixed
`(5.3.5)`. Both APKs install side-by-side; each gets its own
`/data/data/` directory (separate Wine prefix, separate Steam
install, no shared game library).

Mirrors BannerHub upstream's `gamehub.lite` recipe — the rename is a
direct text-manifest edit, not apktool's `renameManifestPackage`
(which leaves authorities pointing at the old package and trips
runtime authority-collision failures).

## Project layout

```
extension/
  BhVibrationController.java       singleton dispatcher (smali entry points,
                                   per-game settings, keepalive thread,
                                   5.3.5 connect-time wake-up)
  BhVibrationSettingsActivity.java Mode/Intensity dialog UI

native/evshim/
  evshim.c, CMakeLists.txt         guest-side LD_PRELOAD shim. Patches
                                   winebus.so's pSDL_JoystickRumble +
                                   pSDL_JoystickClose .bss pointers so
                                   sustained rumble survives SDL's 1 s
                                   auto-expiry. Also writes the
                                   .bh_winedevice_ready marker the host's
                                   wake-up watcher gates on (5.3.5).

scripts/
  apply_vibration_patches.py       smali hooks against a decompiled
                                   apktool tree (5.3.5 or 6.0.2;
                                   version auto-detected from layout).

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone.
