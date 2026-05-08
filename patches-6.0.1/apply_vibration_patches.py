#!/usr/bin/env python3
"""
Apply BannerHub PC-accurate vibration patches to a decompiled GameHub 6.0.1
apktool tree.

GameHub 6.0.1 fixed the multi-controller lazy-attach issue natively, so the
B0 connect hook + GamepadState wake-up reflection are dropped. What remains:

  1. GamepadServerManager.onRumble(III)V  — entry hook (label only changed)
  2. g58.g(II)V                            — controller rumble dispatch
                                             (was GamepadDevice$Physical.h)
  3. g58.f()V                              — stop hook for keepalive cleanup
                                             (was GamepadDevice$Physical.g)
  4. sc5.smali / EnvVars LD_PRELOAD path   — prepend libevshim.so for SDL
                                             1 s auto-expiry keepalive
                                             (sustained rumble fix)

Per-game settings UI insertion is NOT yet ported (popup-menu architecture
in 6.0.1 is restructured; users can still adjust mode via SharedPreferences
or a future UI patch). Settings save/load via the controller still works.

Usage:
    python3 apply_vibration_patches.py <apktool_decompile_dir>

The script is idempotent in failure: if any anchor isn't found it exits
non-zero before mutating anything else.
"""
import sys
from pathlib import Path


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


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(2)

    # Patch 1: GamepadServerManager.onRumble(III)V — short-circuit hook.
    # Anchor is the method header + the first if-ltz guard. Note that 6.0.1
    # uses :cond_4 instead of 5.3.5's :cond_0 here; the rest is unchanged.
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

    # Patch 2: g58.g(II)V — controller dispatch delegate (Physical class
    # equivalent in 6.0.1). Reads deviceId from g58.f:I and hands
    # (deviceId, low, high) to the extension. Returns true → skip stock
    # per-vibrator fallback (which always blends to single-motor).
    patch(
        root / "smali_classes3/g58.smali",
        ".method public final g(II)V\n"
        "    .locals 3\n"
        "\n"
        "    .line 1\n"
        "    const v0, 0xffff\n",
        ".method public final g(II)V\n"
        "    .locals 3\n"
        "\n"
        "    # BH: PC-accurate controller dispatch (dual-motor)\n"
        "    iget v0, p0, Lg58;->f:I\n"
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
        "g58.g(II)V: inject BhVibrationController.dispatchToController"
    )

    # Patch 3: g58.f()V — stop hook. Lets our keepalive map clear when stock
    # GameHub routes (0,0) -> f() instead of g(). 6.0.1 has working instant
    # release natively so we no longer need the Samsung HAL supersede pattern,
    # but onStop still has to fire so the keepalive thread doesn't keep
    # refreshing a controller the game has stopped.
    patch(
        root / "smali_classes3/g58.smali",
        ".method public final f()V\n"
        "    .locals 1\n"
        "\n"
        "    .line 1\n"
        "    iget-object p0, p0, Lg58;->k:Lpfl;\n",
        ".method public final f()V\n"
        "    .locals 1\n"
        "\n"
        "    # BH: notify our keepalive map that this device stopped, then\n"
        "    # fall through to stock cleanup.\n"
        "    iget v0, p0, Lg58;->f:I\n"
        "    invoke-static {v0}, Lcom/xj/winemu/vibration/BhVibrationController;->onStop(I)V\n"
        "\n"
        "    .line 1\n"
        "    iget-object p0, p0, Lg58;->k:Lpfl;\n",
        "g58.f(): inject BhVibrationController.onStop keepalive-map cleanup"
    )

    # Patch 4: sc5.smali — prepend libevshim.so to LD_PRELOAD list.
    # In the LD_PRELOAD building method (sc5.a(Lgyn;Ljava/lang/String;Z)V,
    # .locals 35), v12 is the ArrayList<String> being built and v0 is
    # `this`. Inject just before the joinToString(":") call. Use registers
    # v13..v15 (about to be overwritten anyway by the join setup that
    # follows our injection).
    #
    # Anchor: the unique prefix block setting up the join (v16=0, v17=0x3e,
    # v13=":", v14=0, v15=0) immediately followed by the gr2.B0 call. This
    # only appears once in the entire APK.
    patch(
        root / "smali_classes3/sc5.smali",
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
        "    invoke-static/range {v12 .. v17}, Lgr2;->B0(Ljava/lang/Iterable;Ljava/lang/CharSequence;Ljava/lang/String;Ljava/lang/String;Lxs6;I)Ljava/lang/String;\n",
        "    # BH: prepend libevshim.so to LD_PRELOAD list (guest-side SDL keepalive)\n"
        "    # v0 = this (sc5), v12 = ArrayList<String>. v13..v15 are clobbered\n"
        "    # by the join setup right after this block, so safe to reuse.\n"
        "    iget-object v13, v0, Lsc5;->a:Landroid/content/Context;\n"
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
        "    invoke-static/range {v12 .. v17}, Lgr2;->B0(Ljava/lang/Iterable;Ljava/lang/CharSequence;Ljava/lang/String;Ljava/lang/String;Lxs6;I)Ljava/lang/String;\n",
        "sc5.a(...): prepend libevshim.so to LD_PRELOAD list"
    )

    print("\nAll vibration smali patches applied successfully.")


if __name__ == "__main__":
    main()
