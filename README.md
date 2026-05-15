# GameHub Vibration Fix

> **Built on the shoulders of [BannerHub](https://github.com/The412Banner/BannerHub) by [@The412Banner](https://github.com/The412Banner).**
> The original 5.3.5-based BannerHub project pioneered the apktool-driven
> patching pipeline, smali injection patterns, the guest-side SDL
> keepalive idea, and the vibration-mod architecture this fork is built
> on. If you want the *full* set of GameHub enhancements (Amazon / Epic /
> GOG store integration, Component Manager, RTS touch controls, HUD
> overlays, root access management, frontend export, etc.), use BannerHub
> upstream — that's the real project. This fork is a deliberate strip-down
> of just the vibration mod, supporting stock 5.3.5 and 6.0.4 base APKs.

A minimal patch on top of stock GameHub (5.3.5 or 6.0.4) that adds
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

### One 5.3.5-only exception: `libsdlpreload.so`

5.3.5's stock Wine setup leaves `libSDL2-2.0.so` reachable only via
`libvfs.so`'s private (`RTLD_LOCAL`) namespace. SteamAgent2's Wine PE then
can't resolve SDL symbols cleanly and reports `init_failed=1004` to
GameHub's `SteamAgentServer`, blocking the Steam-button launch path.
6.0.x fixed that natively; 5.3.5 didn't, and BannerHub's old build only
worked because its `libevshim.so` accidentally papered over it as a side
effect of `dlopen("libSDL2-2.0.so", RTLD_NOW|RTLD_GLOBAL)` in its
constructor.

5.3.5 builds ship a tiny constructor-only library
[native/sdlpreload/sdlpreload.c](native/sdlpreload/sdlpreload.c) whose
*only* job is that same `RTLD_GLOBAL` dlopen, plus the BannerHub skip list
(wineserver, services.exe, plugplay.exe, svchost.exe, explorer.exe,
rpcss.exe, tabtip.exe, jwm) to keep libSDL2 out of processes that don't
need it. The 5.3.5 envbuilder smali patch prepends it to `LD_PRELOAD` and
then triggers the disk patcher. No `SDL_JoystickRumble` interpose, no
keepalive thread, no winebus GOT patcher — those features all live in the
disk patch + smali dispatch hooks.

**6.0.4 does not ship `libsdlpreload.so` and adds nothing to `LD_PRELOAD`.**
That's deliberate: the `SK silently exits when anything maps into its Wine
address space` regression only reproduces on 6.0.x. The 6.0.4 build stays
strictly preload-free; the 5.3.5 build trades a single ~2 KB extra mapping
for working Steam launches.

The PC Vibration Settings dialog only controls Mode and Intensity.

## Build

CI workflow: `.github/workflows/build.yml` — triggers on `workflow_dispatch`
(pick base version 5.3.5 / 6.0.4) or push of a `v*-5.3.5*` / `v*-6.0.4*`
tag.

One-time setup per base version: upload the original GameHub APK as an
asset on a release tagged `base-apk-<version>` in this repo (e.g.
`base-apk-6.0.4` for `GameHub_6.0.4_fadf3b5c43f0a3900027758d372b3d54.apk`,
`base-apk-5.3.5` for `GameHub_5.3.5_e5e1b35b774c482a66333afc51eb14b2.apk`).
The workflow `gh release download`s the matching base for the version it
was triggered against.

`scripts/apply_vibration_patches.py` auto-detects the base version from
the smali layout of the decompiled tree:

- **5.3.5** ships unobfuscated symbols under
  `smali_classes7/com/winemu/core/{gamepad,controller}/`.
- **6.0.4** uses ProGuard names `ab8` (Physical), `bg5` (env builder),
  `ps2.I0` (joinToString helper).

Full rename map and per-version anchor set are at the top of the script.
5.3.5's multi-controller wake-up hook (`GamepadManager.B0`) is not
currently restored — single-controller use works without it, but on
multi-controller setups the 2nd/3rd/4th controller needs one button
press after connect to register with libvfs. 6.0.x does not need this.

The pipeline:

1. `apktool d` the base APK
2. Strip `android:usesPermissionFlags` and
   `android:enableOnBackInvokedCallback` from the manifest (apktool 2.9.3's
   bundled aapt2 doesn't know them; cosmetic, harmless — no-op on 5.3.5
   where these attributes don't exist)
3. `python3 scripts/apply_vibration_patches.py` — four smali hooks
4. (optional, **6.0.4 only**) `python3 scripts/apply_login_bypass.py` —
   patch the auth-state combiner + privacy-popup gate
5. `apktool b`
6. `javac + d8` of the two `extension/Bh*.java` files → next free
   `classesN.dex` slot (classes7), inject into the APK
7. `zipalign + apksigner` with `testkey.pk8` / `testkey.x509.pem`
8. Upload as `GameHub-Vibration-Fix-<version>.apk`

## Project layout

```
extension/
  BhVibrationController.java       singleton dispatcher (smali entry points,
                                   per-game settings, keepalive thread,
                                   in-process winebus.so disk patcher).
  BhVibrationSettingsActivity.java Mode/Intensity dialog UI.

native/sdlpreload/
  sdlpreload.c, CMakeLists.txt     5.3.5-only tiny LD_PRELOAD library;
                                   constructor dlopens libSDL2-2.0.so with
                                   RTLD_NOW|RTLD_GLOBAL so SteamAgent2's
                                   Wine PE can resolve SDL symbols. Built
                                   only when CI's base_version=5.3.5.

scripts/
  apply_vibration_patches.py       smali hooks against a decompiled
                                   apktool tree (5.3.5 or 6.0.4;
                                   version auto-detected from layout).
  patch_winebus_rumble_duration.py offline preload-free patch for
                                   extracted winebus.so (aarch64 + x86_64).

.github/workflows/build.yml        CI build pipeline.
```

## What this is not

- Not a continuation of BannerHub. The Amazon / Epic / GOG / Component
  Manager / RTS touch / etc. patches that BannerHub layered on top of
  GameHub are gone.
