#!/usr/bin/env python3
"""
Apply PC-accurate vibration patches to a decompiled GameHub apktool tree.
Supports stock 6.0.1 and 6.0.2 — version is auto-detected from which
obfuscated class names are present. Four hooks:

  1. GamepadServerManager.onRumble(III)V  — entry hook for the dispatcher
                                             (path/anchor identical in
                                             6.0.1 and 6.0.2)
  2. <PhysicalCls>.g(II)V                  — per-controller rumble dispatch
                                             (was GamepadDevice$Physical.h
                                             in 5.3.5; g58 in 6.0.1, za8
                                             in 6.0.2)
  3. <PhysicalCls>.f()V                    — stop hook for keepalive cleanup
                                             (was GamepadDevice$Physical.g
                                             in 5.3.5)
  4. <EnvBuilderCls>.smali LD_PRELOAD path — prepend libevshim.so for SDL
                                             1 s auto-expiry keepalive
                                             (sc5 in 6.0.1, dg5 in 6.0.2)

The 6.0.1 → 6.0.2 ProGuard rename map for the symbols we touch:

    g58 → za8       (Physical class with f:I deviceId field)
    pfl → lrl       (type of the .k field on Physical)
    sc5 → dg5       (LD_PRELOAD/EnvVars builder)
    gr2 → ns2       (CollectionsKt joinTo helper class)
    gr2.B0 → ns2.I0 (joinToString$default)
    xs6 → ow6       (Function1 lambda type used in joinToString)

Per-game settings UI insertion is NOT ported (the 6.0.1+ popup-menu
architecture differs from 5.3.5). Global mode/intensity work fine via
BhVibrationSettingsActivity launched directly.

Usage:
    python3 apply_vibration_patches.py <apktool_decompile_dir>

Fails fast: if any anchor isn't found it exits non-zero before mutating
anything else.
"""
import sys
from pathlib import Path


# ProGuard rename maps keyed by base version. Add a new entry here when a
# future stock release shuffles obfuscated names again.
VERSIONS = {
    "6.0.1": {
        "physical": "g58",     # GamepadDevice$Physical-equivalent class
        "physical_k": "pfl",   # type of <Physical>.k field
        "envbuilder": "sc5",   # LD_PRELOAD env-builder class
        "join_cls": "gr2",     # CollectionsKt joinTo helper
        "join_method": "B0",   # joinToString$default
        "join_lambda": "xs6",  # Function1 lambda parameter type
    },
    "6.0.2": {
        "physical": "za8",
        "physical_k": "lrl",
        "envbuilder": "dg5",
        "join_cls": "ns2",
        "join_method": "I0",
        "join_lambda": "ow6",
    },
}


def detect_version(root: Path) -> tuple[str, dict]:
    """Pick a rename map by checking which obfuscated class files exist.

    Both Physical-class and env-builder class must match the same version
    — if they straddle versions, the apktool tree is inconsistent and we
    bail out rather than attempt half a patch.
    """
    matches = []
    for ver, names in VERSIONS.items():
        phys = root / "smali_classes3" / f"{names['physical']}.smali"
        env = root / "smali_classes3" / f"{names['envbuilder']}.smali"
        if phys.is_file() and env.is_file():
            matches.append(ver)
    if not matches:
        print(
            "ERROR: could not detect GameHub version — none of the known "
            "Physical/env-builder class pairs were found.\n"
            f"Looked under {root}/smali_classes3/ for: "
            + ", ".join(
                f"{n['physical']}.smali+{n['envbuilder']}.smali"
                for n in VERSIONS.values()
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
    ver = matches[0]
    return ver, VERSIONS[ver]


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

    version, names = detect_version(root)
    phys = names["physical"]
    phys_k = names["physical_k"]
    env = names["envbuilder"]
    join_cls = names["join_cls"]
    join_method = names["join_method"]
    join_lambda = names["join_lambda"]
    print(f"Detected GameHub base version: {version}")
    print(f"  Physical class:    {phys} (k:L{phys_k};)")
    print(f"  EnvBuilder class:  {env}")
    print(f"  Join helper:       {join_cls}.{join_method}(...,L{join_lambda};I)")
    print()

    # Patch 1: GamepadServerManager.onRumble(III)V — short-circuit hook.
    # Anchor is the method header + the first if-ltz guard. 6.0.0 used
    # :cond_0 here; 6.0.1 and 6.0.2 both use :cond_4. Identical bytes
    # between 6.0.1 and 6.0.2.
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
    # when stock GameHub routes (0,0) -> f() instead of g(). 6.0.1+ has
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

    print("\nAll vibration smali patches applied successfully.")


if __name__ == "__main__":
    main()
