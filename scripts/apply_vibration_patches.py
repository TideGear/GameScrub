#!/usr/bin/env python3
"""
Apply PC-accurate vibration patches to a decompiled GameHub apktool tree.
Supports stock 5.3.5 and 6.0.2 — version is auto-detected from the smali
class layout.

Hooks (5.3.5 has one extra; 6.0.2 dropped it because the gamepad subsystem
refactor in the 6.0 line fixed the underlying lazy-attach issue natively):

  1. GamepadServerManager.onRumble(III)V  — entry hook for the dispatcher
  2. <Physical>.<dispatch>(II)V            — per-controller rumble dispatch
                                             (h(II)V in 5.3.5; g(II)V in 6.0.2)
  3. <Physical>.<stop>()V                  — stop hook for keepalive cleanup
                                             (g()V in 5.3.5; f()V in 6.0.2)
  4. <EnvBuilder>.smali LD_PRELOAD path    — prepend libevshim.so for SDL
                                             1 s auto-expiry keepalive
  5. GamepadManager.B0(...)V (5.3.5 only)  — connect-time wake-up so libvfs
                                             registers each slot's joystick
                                             before the user touches it
                                             (multi-controller fix)

5.3.5 ships unobfuscated symbols; 6.0.2's ProGuard renames are baked into
RENAMES_6X below.

Per-game settings UI insertion is intentionally out of scope (the 6.0.2
popup-menu architecture differs from 5.3.5; BannerHub upstream has the
5.3.5 version of that). Global mode/intensity work fine via
BhVibrationSettingsActivity launched directly.

Usage:
    python3 apply_vibration_patches.py <apktool_decompile_dir>

Fails fast: if any anchor isn't found it exits non-zero before mutating
anything else.
"""
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Patch primitive
# ---------------------------------------------------------------------------

def patch(path, old, new, label):
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = p.read_text(encoding="latin-1")
    if old not in content:
        print(f"ERROR: anchor not found in {path} for: {label}", file=sys.stderr)
        sys.exit(1)
    p.write_text(content.replace(old, new, 1), encoding="utf-8")
    print(f"OK: {label}")


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

# Each entry maps version -> a (path, must_exist) probe whose presence is a
# reliable signature for that base version's apktool layout.
VERSION_PROBES = {
    "5.3.5": (
        "smali_classes7/com/winemu/core/gamepad/GamepadDevice$Physical.smali",
        "smali_classes7/com/winemu/core/controller/EnvironmentController.smali",
    ),
    "6.0.2": (
        "smali_classes3/za8.smali",
        "smali_classes3/dg5.smali",
    ),
}


def detect_version(root: Path) -> str:
    matches = [
        ver
        for ver, probes in VERSION_PROBES.items()
        if all((root / p).is_file() for p in probes)
    ]
    if not matches:
        print(
            "ERROR: could not detect GameHub version — none of the known "
            "smali layout probes matched.\n"
            "Looked under "
            f"{root}/ for one of:\n  "
            + "\n  ".join(
                f"{ver}: " + " + ".join(VERSION_PROBES[ver])
                for ver in VERSION_PROBES
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"ERROR: ambiguous version detection — matched {matches}. "
            "Two known versions share class names; refusing to guess.",
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


# ---------------------------------------------------------------------------
# 6.0.x patches (parameterised over rename map)
# ---------------------------------------------------------------------------

# Rename maps for the 6.0.x family; same structural patches with the
# obfuscated names swapped in. Currently only 6.0.2 is supported — earlier
# 6.0.x builds (6.0.1) had a different rename set and are no longer
# tracked. To re-enable, add a probe pair to VERSION_PROBES + an entry
# here with the correct obfuscated class names.
RENAMES_6X = {
    "6.0.2": {
        "physical": "za8",     # GamepadDevice$Physical-equivalent class
        "physical_k": "lrl",   # type of <Physical>.k field
        "envbuilder": "dg5",   # LD_PRELOAD env-builder class
        "join_cls": "ns2",     # CollectionsKt joinTo helper
        "join_method": "I0",   # joinToString$default
        "join_lambda": "ow6",  # Function1 lambda parameter type
    },
}


def apply_6x(root: Path, version: str) -> None:
    names = RENAMES_6X[version]
    phys = names["physical"]
    phys_k = names["physical_k"]
    env = names["envbuilder"]
    join_cls = names["join_cls"]
    join_method = names["join_method"]
    join_lambda = names["join_lambda"]
    print(f"  Physical class:    {phys} (k:L{phys_k};)")
    print(f"  EnvBuilder class:  {env}")
    print(f"  Join helper:       {join_cls}.{join_method}(...,L{join_lambda};I)")
    print()

    # Patch 1: GamepadServerManager.onRumble(III)V — short-circuit hook.
    # Anchor is the method header + the first if-ltz guard. 6.0.2 uses
    # :cond_4 here (earlier 6.0.x builds used :cond_0).
    patch(
        root / "smali_classes3/com/winemu/core/gamepad/GamepadServerManager.smali",
        ".method private final onRumble(III)V\n"
        "    .locals 2\n"
        "    .annotation build Landroidx/annotation/Keep;\n"
        "    .end annotation\n"
        "\n"
        "    .line 1\n"
        "    if-ltz p1, :cond_4\n",
        ".method private final onRumble(III)V\n"
        "    .locals 2\n"
        "    .annotation build Landroidx/annotation/Keep;\n"
        "    .end annotation\n"
        "\n"
        "    # BH: PC-accurate rumble dispatcher hook\n"
        "    invoke-static {p1, p2, p3}, Lcom/xj/winemu/vibration/BhVibrationController;->onRumble(III)Z\n"
        "\n"
        "    move-result v0\n"
        "\n"
        "    if-eqz v0, :bh_rumble_fallthrough\n"
        "\n"
        "    return-void\n"
        "\n"
        "    :bh_rumble_fallthrough\n"
        "\n"
        "    .line 1\n"
        "    if-ltz p1, :cond_4\n",
        "GamepadServerManager.onRumble(III)V: inject BhVibrationController entry hook"
    )

    # Patch 2: <Physical>.g(II)V — controller dispatch delegate. Reads
    # deviceId from <Physical>.f:I and hands (deviceId, low, high) to the
    # extension. Returns true → skip stock per-vibrator fallback (which
    # always blends to single-motor).
    patch(
        root / f"smali_classes3/{phys}.smali",
        ".method public final g(II)V\n"
        "    .locals 3\n"
        "\n"
        "    .line 1\n"
        "    const v0, 0xffff\n",
        ".method public final g(II)V\n"
        "    .locals 3\n"
        "\n"
        "    # BH: PC-accurate controller dispatch (dual-motor)\n"
        f"    iget v0, p0, L{phys};->f:I\n"
        "\n"
        "    invoke-static {v0, p1, p2}, Lcom/xj/winemu/vibration/BhVibrationController;->dispatchToController(III)Z\n"
        "\n"
        "    move-result v0\n"
        "\n"
        "    if-eqz v0, :bh_phys_fallthrough\n"
        "\n"
        "    return-void\n"
        "\n"
        "    :bh_phys_fallthrough\n"
        "\n"
        "    .line 1\n"
        "    const v0, 0xffff\n",
        f"{phys}.g(II)V: inject BhVibrationController.dispatchToController"
    )

    # Patch 3: <Physical>.f()V — stop hook. Lets our keepalive map clear
    # when stock GameHub routes (0,0) -> f() instead of g(). 6.0.x has
    # working instant release natively so we no longer need the Samsung
    # HAL supersede pattern, but onStop still has to fire so the keepalive
    # thread doesn't keep refreshing a controller the game has stopped.
    patch(
        root / f"smali_classes3/{phys}.smali",
        ".method public final f()V\n"
        "    .locals 1\n"
        "\n"
        "    .line 1\n"
        f"    iget-object p0, p0, L{phys};->k:L{phys_k};\n",
        ".method public final f()V\n"
        "    .locals 1\n"
        "\n"
        "    # BH: notify our keepalive map that this device stopped, then\n"
        "    # fall through to stock cleanup.\n"
        f"    iget v0, p0, L{phys};->f:I\n"
        "    invoke-static {v0}, Lcom/xj/winemu/vibration/BhVibrationController;->onStop(I)V\n"
        "\n"
        "    .line 1\n"
        f"    iget-object p0, p0, L{phys};->k:L{phys_k};\n",
        f"{phys}.f(): inject BhVibrationController.onStop keepalive-map cleanup"
    )

    # Patch 4: <EnvBuilder>.smali — prepend libevshim.so to LD_PRELOAD list.
    # In the LD_PRELOAD building method (a(L<...>;Ljava/lang/String;Z)V,
    # .locals 35), v12 is the ArrayList<String> being built and v0 is
    # `this`. Inject just before the joinToString(":") call. Use registers
    # v13..v15 (about to be overwritten anyway by the join setup that
    # follows our injection).
    #
    # Anchor: the unique prefix block setting up the join (v16=0, v17=0x3e,
    # v13=":", v14=0, v15=0) immediately followed by the joinToString$default
    # call. This appears once in the entire APK.
    join_signature = (
        f"L{join_cls};->{join_method}"
        f"(Ljava/lang/Iterable;Ljava/lang/CharSequence;Ljava/lang/String;"
        f"Ljava/lang/String;L{join_lambda};I)Ljava/lang/String;"
    )
    patch(
        root / f"smali_classes3/{env}.smali",
        "    const/16 v16, 0x0\n"
        "\n"
        "    .line 458\n"
        "    .line 459\n"
        "    const/16 v17, 0x3e\n"
        "\n"
        "    .line 460\n"
        "    .line 461\n"
        "    const-string v13, \":\"\n"
        "\n"
        "    .line 462\n"
        "    .line 463\n"
        "    const/4 v14, 0x0\n"
        "\n"
        "    .line 464\n"
        "    const/4 v15, 0x0\n"
        "\n"
        "    .line 465\n"
        f"    invoke-static/range {{v12 .. v17}}, {join_signature}\n",
        "    # BH: prepend libevshim.so to LD_PRELOAD list (guest-side SDL keepalive)\n"
        f"    # v0 = this ({env}), v12 = ArrayList<String>. v13..v15 are clobbered\n"
        "    # by the join setup right after this block, so safe to reuse.\n"
        f"    iget-object v13, v0, L{env};->a:Landroid/content/Context;\n"
        "    invoke-virtual {v13}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;\n"
        "    move-result-object v13\n"
        "    iget-object v13, v13, Landroid/content/pm/ApplicationInfo;->nativeLibraryDir:Ljava/lang/String;\n"
        "    new-instance v14, Ljava/lang/StringBuilder;\n"
        "    invoke-direct {v14}, Ljava/lang/StringBuilder;-><init>()V\n"
        "    invoke-virtual {v14, v13}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n"
        "    const-string v13, \"/libevshim.so\"\n"
        "    invoke-virtual {v14, v13}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n"
        "    invoke-virtual {v14}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n"
        "    move-result-object v13\n"
        "    new-instance v14, Ljava/io/File;\n"
        "    invoke-direct {v14, v13}, Ljava/io/File;-><init>(Ljava/lang/String;)V\n"
        "    invoke-virtual {v14}, Ljava/io/File;->exists()Z\n"
        "    move-result v15\n"
        "    if-eqz v15, :bh_skip_evshim_preload\n"
        "    const/4 v15, 0x0\n"
        "    invoke-virtual {v12, v15, v13}, Ljava/util/ArrayList;->add(ILjava/lang/Object;)V\n"
        "    :bh_skip_evshim_preload\n"
        "\n"
        "    const/16 v16, 0x0\n"
        "\n"
        "    .line 458\n"
        "    .line 459\n"
        "    const/16 v17, 0x3e\n"
        "\n"
        "    .line 460\n"
        "    .line 461\n"
        "    const-string v13, \":\"\n"
        "\n"
        "    .line 462\n"
        "    .line 463\n"
        "    const/4 v14, 0x0\n"
        "\n"
        "    .line 464\n"
        "    const/4 v15, 0x0\n"
        "\n"
        "    .line 465\n"
        f"    invoke-static/range {{v12 .. v17}}, {join_signature}\n",
        f"{env}.a(...): prepend libevshim.so to LD_PRELOAD list"
    )


# ---------------------------------------------------------------------------
# 5.3.5 patches
# ---------------------------------------------------------------------------

# Stock 5.3.5 ships unobfuscated symbol names — all five anchors live under
# smali_classes7/com/winemu/core/{controller,gamepad}/. Method names differ
# from 6.0.x: dispatch is .h(II)V and stop is .g()V. The deviceId field
# is .d:I rather than .f:I. The LD_PRELOAD env builder is the named
# EnvironmentController class (no joinToString helper — uses a List directly,
# so the inject site is right before EnvVars.f("LD_PRELOAD", v1)). And there
# is one extra hook (GamepadManager.B0) to wake libvfs's lazy SDL joystick
# registration on each controller-connect, which the 6.0 line fixed natively.

def apply_535(root: Path) -> None:
    print("  Layout:           smali_classes7/com/winemu/core/{controller,gamepad}/")
    print("  Symbols:          stock 5.3.5 ships unobfuscated.")
    print()

    # Patch 1: GamepadServerManager.onRumble(III)V — entry hook.
    # 5.3.5's `if-ltz` guard targets :cond_0 (vs :cond_4 in 6.0.x);
    # otherwise structurally identical to the 6.0.x patch.
    patch(
        root / "smali_classes7/com/winemu/core/gamepad/GamepadServerManager.smali",
        ".method private final onRumble(III)V\n"
        "    .locals 2\n"
        "    .annotation build Landroidx/annotation/Keep;\n"
        "    .end annotation\n"
        "\n"
        "    .line 1\n"
        "    if-ltz p1, :cond_0\n",
        ".method private final onRumble(III)V\n"
        "    .locals 2\n"
        "    .annotation build Landroidx/annotation/Keep;\n"
        "    .end annotation\n"
        "\n"
        "    # BH: PC-accurate rumble dispatcher hook\n"
        "    invoke-static {p1, p2, p3}, Lcom/xj/winemu/vibration/BhVibrationController;->onRumble(III)Z\n"
        "\n"
        "    move-result v0\n"
        "\n"
        "    if-eqz v0, :bh_rumble_fallthrough\n"
        "\n"
        "    return-void\n"
        "\n"
        "    :bh_rumble_fallthrough\n"
        "\n"
        "    .line 1\n"
        "    if-ltz p1, :cond_0\n",
        "GamepadServerManager.onRumble(III)V: inject BhVibrationController entry hook"
    )

    # Patch 2: GamepadDevice$Physical.h(II)V — controller dispatch delegate.
    # deviceId is in field d:I in 5.3.5 (vs f:I in 6.0.x). Same skip-stock-
    # fallback semantics as the 6.0.x patch.
    patch(
        root / "smali_classes7/com/winemu/core/gamepad/GamepadDevice$Physical.smali",
        ".method public h(II)V\n"
        "    .locals 3\n"
        "\n"
        "    .line 1\n"
        "    const v0, 0xffff\n",
        ".method public h(II)V\n"
        "    .locals 3\n"
        "\n"
        "    # BH: PC-accurate controller dispatch (dual-motor)\n"
        "    iget v0, p0, Lcom/winemu/core/gamepad/GamepadDevice$Physical;->d:I\n"
        "\n"
        "    invoke-static {v0, p1, p2}, Lcom/xj/winemu/vibration/BhVibrationController;->dispatchToController(III)Z\n"
        "\n"
        "    move-result v0\n"
        "\n"
        "    if-eqz v0, :bh_phys_fallthrough\n"
        "\n"
        "    return-void\n"
        "\n"
        "    :bh_phys_fallthrough\n"
        "\n"
        "    .line 1\n"
        "    const v0, 0xffff\n",
        "GamepadDevice$Physical.h(II)V: inject BhVibrationController.dispatchToController"
    )

    # Patch 3: GamepadDevice$Physical.g()V — stop hook. Stock f(II)V routes
    # (0,0) -> g() and non-zero -> h(II)V; Patch 2 only catches h, so (0,0)
    # would bypass the keepalive otherwise. onStop is void; on 5.3.5 it
    # also issues the Samsung-HAL pre-cancel supersede before falling
    # through to stock g() (which iterates vibrators and cancels each).
    patch(
        root / "smali_classes7/com/winemu/core/gamepad/GamepadDevice$Physical.smali",
        ".method public g()V\n"
        "    .locals 1\n"
        "\n"
        "    .line 1\n"
        "    invoke-virtual {p0}, Lcom/winemu/core/gamepad/GamepadDevice$Physical;->o()Ljava/util/List;\n",
        ".method public g()V\n"
        "    .locals 1\n"
        "\n"
        "    # BH: dispatch to our handler (supersede pattern), then fall through.\n"
        "    iget v0, p0, Lcom/winemu/core/gamepad/GamepadDevice$Physical;->d:I\n"
        "    invoke-static {v0}, Lcom/xj/winemu/vibration/BhVibrationController;->onStop(I)V\n"
        "\n"
        "    .line 1\n"
        "    invoke-virtual {p0}, Lcom/winemu/core/gamepad/GamepadDevice$Physical;->o()Ljava/util/List;\n",
        "GamepadDevice$Physical.g(): inject BhVibrationController.onStop pre-cancel supersede"
    )

    # Patch 4: EnvironmentController.b(Wine, String) — prepend libevshim.so
    # to the LD_PRELOAD list. 5.3.5's env-builder uses a plain List<String>
    # passed in v1 (not the v12 ArrayList of 6.0.x's joinToString flow), so
    # the register layout differs — we use v2/v3 here. Anchor is the
    # `:cond_2 :goto_1 const-string v2, "LD_PRELOAD"` join point right
    # before EnvVars.f("LD_PRELOAD", v1).
    patch(
        root / "smali_classes7/com/winemu/core/controller/EnvironmentController.smali",
        "    :cond_2\n"
        "    :goto_1\n"
        "    const-string v2, \"LD_PRELOAD\"\n",
        "    :cond_2\n"
        "    :goto_1\n"
        "\n"
        "    # BH: prepend libevshim.so to LD_PRELOAD list (guest-side SDL keepalive)\n"
        "    iget-object v2, p0, Lcom/winemu/core/controller/EnvironmentController;->a:Landroid/content/Context;\n"
        "    invoke-virtual {v2}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;\n"
        "    move-result-object v2\n"
        "    iget-object v2, v2, Landroid/content/pm/ApplicationInfo;->nativeLibraryDir:Ljava/lang/String;\n"
        "    new-instance v3, Ljava/lang/StringBuilder;\n"
        "    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V\n"
        "    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n"
        "    const-string v2, \"/libevshim.so\"\n"
        "    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n"
        "    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n"
        "    move-result-object v2\n"
        "    new-instance v3, Ljava/io/File;\n"
        "    invoke-direct {v3, v2}, Ljava/io/File;-><init>(Ljava/lang/String;)V\n"
        "    invoke-virtual {v3}, Ljava/io/File;->exists()Z\n"
        "    move-result v3\n"
        "    if-eqz v3, :bh_skip_evshim_preload\n"
        "    const/4 v3, 0x0\n"
        "    invoke-interface {v1, v3, v2}, Ljava/util/List;->add(ILjava/lang/Object;)V\n"
        "    :bh_skip_evshim_preload\n"
        "\n"
        "    const-string v2, \"LD_PRELOAD\"\n",
        "EnvironmentController.b(Wine, String): prepend libevshim.so to LD_PRELOAD"
    )

    # Patch 5: GamepadManager.B0(GamepadConnectionEvent)V — connect-time
    # wake-up. On 5.3.5, libvfs lazily registers the virtual SDL joystick
    # and only emits SDL_JOYDEVICEADDED on first input — until then,
    # winebus.so has the slot closed and rumble dispatches silently no-op.
    # Multi-controller users see the second/Nth controller's rumble fail
    # until they press any button on it.
    #
    # BhVibrationController.scheduleWakeup queues a button-14 flicker on the
    # slot's GamepadState gated on libevshim's winedevice ready marker;
    # drainPendingWakeups fires staggered (200 ms per slot, ascending) so
    # libvfs registers each slot before the next.
    #
    # Only run for GamepadDevice$Physical: the virtual touch-controls
    # gamepad does NOT need a libvfs lazy-attach trigger, and calling
    # GamepadSlotManager.m() on it has a side-effect of pre-registering the
    # slot which then makes stock B0's own registration throw "Virtual
    # gamepad already exists in slot 0", leaving GamepadManager broken and
    # crashing WineActivity later with "Virtual gamepad enabled but no
    # controller found".
    #
    # 6.0.x doesn't need this — the 6.0 gamepad-subsystem refactor fixed
    # the lazy-attach issue natively, so this patch is 5.3.5-only.
    patch(
        root / "smali_classes7/com/winemu/core/gamepad/GamepadManager.smali",
        ".method public B0(Lcom/winemu/core/gamepad/GamepadConnectionEvent;)V\n"
        "    .locals 4\n"
        "\n"
        "    .line 1\n"
        "    const-string v0, \"event\"\n",
        ".method public B0(Lcom/winemu/core/gamepad/GamepadConnectionEvent;)V\n"
        "    .locals 4\n"
        "\n"
        "    # BH: schedule synthetic wake-up so libvfs registers this slot\n"
        "    # with SDL before the user presses anything. Physical-only — the\n"
        "    # virtual gamepad pre-registers as a side-effect of\n"
        "    # GamepadSlotManager.m() and would conflict with stock B0 below.\n"
        "    invoke-virtual {p1}, Lcom/winemu/core/gamepad/GamepadConnectionEvent;->a()Lcom/winemu/core/gamepad/GamepadDevice;\n"
        "    move-result-object v0\n"
        "    if-eqz v0, :bh_wakeup_skip\n"
        "    instance-of v3, v0, Lcom/winemu/core/gamepad/GamepadDevice$Physical;\n"
        "    if-eqz v3, :bh_wakeup_skip\n"
        "    iget-object v1, p0, Lcom/winemu/core/gamepad/GamepadManager;->e:Lcom/winemu/core/gamepad/GamepadSlotManager;\n"
        "    invoke-virtual {v1, v0}, Lcom/winemu/core/gamepad/GamepadSlotManager;->m(Lcom/winemu/core/gamepad/GamepadDevice;)I\n"
        "    move-result v1\n"
        "    iget-object v2, p0, Lcom/winemu/core/gamepad/GamepadManager;->c:Lcom/winemu/core/gamepad/GamepadServerManager;\n"
        "    invoke-static {v2, v1}, Lcom/xj/winemu/vibration/BhVibrationController;->scheduleWakeup(Ljava/lang/Object;I)V\n"
        "    :bh_wakeup_skip\n"
        "\n"
        "    .line 1\n"
        "    const-string v0, \"event\"\n",
        "GamepadManager.B0(): inject BhVibrationController.scheduleWakeup post-connect"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(2)

    version = detect_version(root)
    print(f"Detected GameHub base version: {version}")

    if version == "5.3.5":
        apply_535(root)
    elif version in RENAMES_6X:
        apply_6x(root, version)
    else:
        # Unreachable: detect_version already validated.
        print(f"ERROR: no patch path implemented for {version}", file=sys.stderr)
        sys.exit(1)

    print("\nAll vibration smali patches applied successfully.")


if __name__ == "__main__":
    main()
