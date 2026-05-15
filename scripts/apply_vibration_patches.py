#!/usr/bin/env python3
"""
Apply PC-accurate vibration patches to a decompiled GameHub apktool tree.
Supports stock 6.0.2 and 6.0.4 — version is auto-detected from the
smali class layout.

Hooks:

  1. GamepadServerManager.onRumble(III)V  — entry hook for the dispatcher
  2. <Physical>.g(II)V                     — per-controller rumble dispatch
  3. <Physical>.f()V                       — stop hook for keepalive cleanup
  4. <EnvBuilder>.smali LD_PRELOAD path    — prepend libevgate.so, which
                                             loads libevshim.so only inside
                                             winedevice.exe

Per-version ProGuard rename maps are baked into RENAMES_6X below.

Per-game settings UI insertion is intentionally out of scope (the 6.0.x
popup-menu architecture is Compose-based and Tencent's R8 obfuscation
makes the entry points hard to reach reliably). Global mode/intensity
work fine via BhVibrationSettingsActivity launched directly.

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
    "6.0.2": (
        "smali_classes3/za8.smali",
        "smali_classes3/dg5.smali",
    ),
    "6.0.4": (
        "smali_classes3/ab8.smali",
        "smali_classes3/bg5.smali",
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
    "6.0.4": {
        "physical": "ab8",
        "physical_k": "xrl",
        "envbuilder": "bg5",
        "join_cls": "ps2",
        "join_method": "I0",
        "join_lambda": "pw6",
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

    # Patch 4: <EnvBuilder>.smali — prepend libevgate.so to LD_PRELOAD list.
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
        "    # BH: prepend libevgate.so to LD_PRELOAD list (winedevice-only SDL keepalive)\n"
        f"    # v0 = this ({env}), v12 = ArrayList<String>. v13..v15 are clobbered\n"
        "    # by the join setup right after this block, so safe to reuse.\n"
        "    #\n"
        "    # BhVibrationController currently defaults this on unconditionally\n"
        "    # so stale per-game/global prefs cannot disable the SK test path.\n"
        "    # libevgate itself is mapped process-wide, but it dlopen()s\n"
        "    # libevshim.so only when /proc/self/cmdline is winedevice.exe.\n"
        f"    iget-object v13, v0, L{env};->a:Landroid/content/Context;\n"
        "    invoke-static {v13}, Lcom/xj/winemu/vibration/BhVibrationController;->shouldPreloadEvshim(Landroid/content/Context;)Z\n"
        "    move-result v14\n"
        "    if-eqz v14, :bh_skip_evshim_preload\n"
        "\n"
        "    invoke-virtual {v13}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;\n"
        "    move-result-object v13\n"
        "    iget-object v13, v13, Landroid/content/pm/ApplicationInfo;->nativeLibraryDir:Ljava/lang/String;\n"
        "    new-instance v14, Ljava/lang/StringBuilder;\n"
        "    invoke-direct {v14}, Ljava/lang/StringBuilder;-><init>()V\n"
        "    invoke-virtual {v14, v13}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n"
        "    const-string v13, \"/libevgate.so\"\n"
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
        f"{env}.a(...): prepend libevgate.so to LD_PRELOAD list"
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

    if version in RENAMES_6X:
        apply_6x(root, version)
    else:
        # Unreachable: detect_version already validated.
        print(f"ERROR: no patch path implemented for {version}", file=sys.stderr)
        sys.exit(1)

    print("\nAll vibration smali patches applied successfully.")


if __name__ == "__main__":
    main()
