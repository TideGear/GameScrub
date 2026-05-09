# GameHub 6.0.1 — Vibration Mod

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, libevshim guest-side SDL
> keepalive, and the entire vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> of just the vibration mod onto a 6.0.1 base.

A minimal patch on top of stock GameHub 6.0.1 that adds **PC-accurate XInput
rumble support** for Wine games. Nothing else is changed.

What you get over stock 6.0.1:

- **Dual-motor low/high dispatch.** Wine games calling `XInputSetState(slot,
  low, high)` get the two motors driven independently via Android
  `CombinedVibration.startParallel` on ≥ 2-motor controllers. Stock 6.0.1
  blends both motors into a single haptic pulse; this preserves the heavy
  / light distinction the way the game intended.
- **Sustained rumble holds past 1 s.** SDL2's internal 1 s
  `rumble_expiration` auto-stops sustained rumble on stock; an LD_PRELOAD
  shim (`libevshim.so`) re-issues `SDL_JoystickRumble` every 500 ms with a
  2 s duration so the timer never fires.
- **Instant release** when the game stops rumble — no phantom-suppression
  timer extending the motor past the actual stop call.
- **Per-game Mode/Intensity settings** (Off / Controller / Device / Both,
  0–100 %) via `BhVibrationSettingsActivity`. Settings persist in
  `pc_g_setting<gameId>` SharedPreferences so they round-trip with stock
  Export/Import Config.

Multi-controller support and the connect-time wake-up that the 5.3.5 mod
needed are dropped in this 6.0.1 build — the 6.0.1 gamepad subsystem
refactor fixed the lazy-attach issue natively.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
or push of a `v*-6.0.1*` tag.

One-time setup: upload the original
`GameHub_6.0.1_3c8906664cbe65b4c9f3c36eadb5c406.apk` (or whichever 6.0.1
build you're targeting) as an asset on a release tagged `base-apk-6.0.1`
in this repo. The workflow runs `gh release download base-apk-6.0.1` to
fetch it.

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
                                   6.0.1 apktool tree.

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone. This fork ships **only the vibration mod**.
- Not a 5.3.5 build. The 5.3.5 vibration port lives on the
  `Fix-Vibration` branch and is preserved there for reference. (Stock
  GameHub 6.0.1's Steam integration handles achievements natively, and
  our patches don't touch the Steam code paths, so achievements should
  work in this fork the same as on stock 6.0.1.)
