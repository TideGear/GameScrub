# BannerHub Vibration Patches — GameHub 6.0.1

This directory ports the BannerHub PC-accurate vibration mod from GameHub 5.3.5
to GameHub 6.0.1. The 6.0.1 gamepad subsystem refactor fixed several issues
the original mod worked around, so this port is significantly slimmer.

## What's in vs out vs 5.3.5

| Component | 5.3.5 | 6.0.1 |
|---|---|---|
| `GamepadServerManager.onRumble` hook (entry point) | ✓ | ✓ (label tweak) |
| `g58.g(II)V` controller dispatch (was `Physical.h`) | ✓ | ✓ |
| `g58.f()V` stop hook (was `Physical.g`) | ✓ | ✓ (keepalive cleanup only — Samsung HAL supersede kept defensively) |
| `libevshim.so` LD_PRELOAD (SDL 1 s auto-expiry keepalive) | ✓ | ✓ — `sc5.smali` instead of `EnvironmentController` |
| `GamepadManager.B0` connect hook + wake-up | ✓ | **dropped** — 6.0.1 fixed lazy-attach natively |
| `GamepadState` button-flicker reflection | ✓ | **dropped** |
| Per-game settings popup option | ✓ | **deferred** — popup menu architecture changed; needs separate work |

## Files

- `apply_vibration_patches.py` — Python script that patches a decompiled
  6.0.1 apktool tree. Idempotent; aborts on missing anchor before mutating.
- `BhVibrationController.java` — slim port of the dispatcher. Drops ~200
  lines of wake-up infrastructure.
- `BhVibrationSettingsActivity.java` — unchanged from 5.3.5.
- `evshim/` — unchanged guest-side LD_PRELOAD shim (`evshim.c`,
  `CMakeLists.txt`).

## Apply manually

```bash
# 1. Decompile the 6.0.1 APK
java -jar apktool.jar d GameHub_6.0.1_*.apk -o gh-601 -f

# 2. Drop our extension files into the smali tree (compile-time placeholder
#    paths — these need to be smali-compiled separately or copied as Java
#    sources into the build pipeline).
cp BhVibrationController.java BhVibrationSettingsActivity.java <build_root>/extension/

# 3. Build libevshim.so for arm64-v8a from evshim/ using NDK
#    (cd evshim && cmake ... && make)
#    drop the resulting libevshim.so into <build_root>/lib/arm64-v8a/

# 4. Apply smali patches
python3 apply_vibration_patches.py gh-601

# 5. Reassemble + sign
java -jar apktool.jar b gh-601 -o GameHub_6.0.1_BhVib.apk
# (zipalign + apksigner steps as usual)
```

## Known gaps in this port

- **No per-game settings UI yet.** The 6.0.1 popup options menu is in a
  different place than 5.3.5's `GameDetailSettingMenu.W()`; finding the
  new injection point is TODO. Until that lands, the user adjusts global
  defaults via `bh_vibration_prefs` SharedPreferences directly.
- **Per-game prefs path may need updating.** 5.3.5 stored per-game vibration
  settings in `pc_g_setting<gameId>` so they round-tripped through the
  Export/Import Config flow. 6.0.1 may have moved this file too — verify
  before relying on import/export integration.
- **Untested.** This port hasn't been built or run against 6.0.1 on a real
  device yet. Anchor failures will show up during the patch-script step;
  runtime behaviour needs logcat verification.
