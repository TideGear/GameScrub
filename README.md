# GameScrub

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, the guest-side SDL
> keepalive idea, and the vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> to just the vibration fix plus the privacy patch set, supporting stock 6.0.4.

A minimal patch on top of stock GameHub 6.0.4 that adds
**PC-accurate XInput rumble support** for Wine games and **strips
unnecessary telemetry**. Otherwise unchanged from upstream. The point is
to keep stock GameHub's working achievements / library / online features
while fixing vibration and silencing the XiaoJi / Firebase / Mob /
Google analytics channels.

What you get over stock GameHub:

- **Dual-motor low/high dispatch.** Wine games calling `XInputSetState(slot,
  low, high)` get the two motors driven independently via Android
  `CombinedVibration.startParallel` on ≥ 2-motor controllers. Stock GameHub
  blends both motors into a single haptic pulse; this preserves the heavy
  / light distinction the way the game intended.
- **Sustained rumble holds past 1 s.** SDL2's internal 1 s
  `rumble_expiration` auto-stops sustained rumble on stock. The APK's
  launch-time Java hook patches every app-owned `winebus.so` on disk so
  the two non-zero `SDL_JoystickRumble` call sites pass `0xffffffff` as
  the SDL duration; zero-duration stop calls still stop immediately. No
  `LD_PRELOAD`, no extra `.so` mapped into the Wine subprocess address
  space. The offline helper
  [scripts/patch_winebus_rumble_duration.py](scripts/patch_winebus_rumble_duration.py)
  applies the same patch to extracted components for offline use.
- **Instant release** when the game stops rumble — no phantom-suppression
  timer extending the motor past the actual stop call.
- **Privacy patches** — port of bannerhub-revanced's privacy patch set.
  Kills Firebase Analytics, Google Play Services Measurement, Mob Push
  SDK, the XiaoJi heartbeat / playtime tracker, both vgabc.com /events
  endpoints, and the JieLi OTA phone-home. Steam / GOG / Epic / Wine /
  account login are untouched. Full channel list in
  [scripts/apply_privacy_patches.py](scripts/apply_privacy_patches.py).

### Preload-free architecture

Earlier builds preloaded `libevshim.so` (and later a tiny gate library
`libevgate.so`) into every Wine subprocess to interpose `SDL_JoystickRumble`
at runtime. A small set of games silently exit at launch when *any* extra
`.so` is mapped into their Wine subprocess address space — verified to be
pure mmap presence rather than symbol exports or constructor side effects.
Wine's preloader is famously fussy about address-space layout, and the
canonical case here is **Shotgun King: The Final Checkmate** (GameMaker
Studio 2), which exited ~700 ms after `boot job completed` with
`normalExit=true` and no tombstone whenever an extra preload was present.

The current build avoids that entire failure mode by patching `winebus.so`
on disk and adding nothing to `LD_PRELOAD`. The smali envbuilder patch
([scripts/apply_vibration_patches.py](scripts/apply_vibration_patches.py))
calls [BhVibrationController.ensureWinebusDurationPatchOnce()](extension/BhVibrationController.java)
once per app process, immediately before the env builder hands off to the
Wine launcher. The Java side scans the files tree for every `winebus.so`
and rewrites the duration loads in place; an `AtomicBoolean` gates against
repeat scans.

Both aarch64-unix and x86_64-unix `winebus.so` variants are patched. The
aarch64 path rewrites `ldur w3,[x29,#-0x14]; blr x8` to `mov w3,#-1; blr x8`.
The x86_64 path matches an 11-byte clang/NDK-r26 codegen window (`mov ecx,
[rbp+disp8]; movzwl si,esi; movzwl dx,edx; call *%rax`) and replaces the
3-byte duration load with `or ecx, -1`. If the x86_64 pattern ever misses
on a future proton build, the patcher writes the file to
`<externalFilesDir>/winebus_dump_x86_64.so` so the new codegen can be
inspected with `adb pull` and the pattern refined.

The PC Vibration Settings dialog only controls Mode and Intensity.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
or push of a `v*-6.0.4*` tag.

One-time setup: upload the original GameHub APK as an asset on a release
tagged `base-apk-6.0.4` in this repo (e.g.
`GameHub_6.0.4_fadf3b5c43f0a3900027758d372b3d54.apk`). The workflow
`gh release download`s from there.

`scripts/apply_vibration_patches.py` patches stock 6.0.4 using the
ProGuard names `ab8` (Physical), `bg5` (env builder), `ps2.I0`
(joinToString helper). Full anchor set and rename map are at the top of
the script.

`scripts/apply_privacy_patches.py` is a port of the bannerhub-revanced
privacy patch set. Manifest layer adds Firebase kill-switch meta-data,
disables Google Play Services Measurement components, strips ad-ID
permission declarations, disables every Mob / cn.fly component, and
removes the JieLi gamepad-firmware native libs. Smali layer stubs the
two `statistic-gamehub-api.vgabc.com` event endpoints, the four
heartbeat/playtime methods, the OTA URL register, and the three Mob SDK
bootstrap invokes. Anchors and the full deliberate-skip list live at the
top of the script. Trade-off worth flagging: GameHub's in-app per-game
playtime UI renders empty (Steam's own playtime on your Steam profile
is unaffected — Steam tracks playtime independently).

The pipeline:

1. `apktool d` the base APK
2. Strip `android:usesPermissionFlags` and
   `android:enableOnBackInvokedCallback` from the manifest (apktool 2.9.3's
   bundled aapt2 doesn't know them; cosmetic, harmless)
3. `python3 scripts/apply_vibration_patches.py` — four smali hooks
4. `python3 scripts/apply_privacy_patches.py` — manifest + smali +
   native-lib strip
5. `apktool b`
6. `javac + d8` of the two `extension/Bh*.java` files → next free
   `classesN.dex` slot (classes7), inject into the APK
7. `zipalign + apksigner` with `testkey.pk8` / `testkey.x509.pem`
8. Upload as `GameScrub-6.0.4.apk`

## Project layout

```
extension/
  BhVibrationController.java       singleton dispatcher (smali entry points,
                                   per-game settings, keepalive thread,
                                   in-process winebus.so disk patcher).
  BhVibrationSettingsActivity.java Mode/Intensity dialog UI.

scripts/
  apply_vibration_patches.py       smali hooks against a decompiled
                                   GameHub 6.0.4 apktool tree.
  apply_privacy_patches.py         manifest + smali + native-lib edits
                                   that kill Firebase / GMS Measurement
                                   / Mob Push / XiaoJi events + heartbeat
                                   / JieLi OTA.
  patch_winebus_rumble_duration.py offline preload-free patch for
                                   extracted winebus.so (aarch64 + x86_64).

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone.
