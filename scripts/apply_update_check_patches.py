#!/usr/bin/env python3
"""
Wire the background Steam update-badge checker into GameHub 6.1.1/6.1.2.

Stock GameHub only runs the Steam "Online Update" check on a couple of lazy
paths (an event handler Lp1a;->o dispatching Lvi0;->o(appId, flag) + a few
detail/refresh flows) and the badges just read the last cached result, so the
red dot lags behind reality — users can launch a game several times before an
available update shows up. 6.1.1 added per-app cooldown maps (30 min / 60 s,
inside Lwvo;->w) but still has no periodic sweep, so the trigger-frequency gap
is unchanged. The check is really a network query to Steam's Content Manager
via GameHub's embedded native Steam client bridge; it does NOT require the game
(Wine) to be running, only that the app is open and the Steam session is
connected. So a background sweep is viable.

6.1.1 note: the PC engine moved into a runtime-downloaded plugin and now runs
in a ":pcengine" process. onCreate runs in every process, so start() is called
there too; it is fail-soft (the Steam bridge and its reflection anchors simply
aren't resolvable there, which logs and retries) and the Steam session lives in
the main process regardless.

This script injects a single call into the Application's onCreate so
com.xj.winemu.update.BhSteamUpdateChecker starts its background worker once
per app process. Everything else (enumerating installed appIds, running the
host's own per-app check via the withContext reflection bridge, refreshing
the badge flow) lives in the Java extension class — no other smali edits.

Injection
---------
  Lcom/xiaoji/egggame/AndroidApp;->onCreate()V   (Application subclass)

We anchor on the `sput-object vN, L<holder>;->f:...AndroidApp;` line that stock
onCreate runs immediately after super.onCreate() — at that point super has
run and that register holds the Application (a Context). We insert our
start(Context) call right after it. onCreate is .locals 71, so there is no
register pressure and no .locals bump. Fails loudly if the anchor is missing or
the Application class moved (base bump) so a broken build never ships silently.

The holder class and field are R8 letters and drift every release (6.1.1
Lrs1;->s / Lp44;->a, 6.1.2 Lss1;->s / Lr44;->a), so they are wildcarded — what
is actually stable is the *shape*: a static store of the AndroidApp instance,
whose type name R8 keeps. There are TWO such lines in onCreate; we pin the
FIRST, which is the one directly after super.onCreate(), and assert the count
matches what we have seen so a third one appearing forces a look rather than a
silent shift.

The BhSteamUpdateChecker Java is compiled + dex'd in the same workflow step
as the other extension/ classes.
"""
import re
import sys
from pathlib import Path


# --- Real base version, read from the tree rather than inferred ------------
# The structural probes below cannot tell 6.1.1 from 6.1.2: both ship the
# plugin host activity and the same smali layout. apktool.yml carries the
# actual versionName, so report that and keep the probes for the *family*
# decision (plugin-era vs base-APK-engine).
SUPPORTED_BASES = ("6.1.1", "6.1.2", "6.2.0", "6.2.1", "6.3.0")


def apktool_version(root: Path):
    """versionName from apktool.yml, or None if unreadable."""
    y = Path(root) / "apktool.yml"
    if not y.is_file():
        return None
    try:
        m = re.search(r"^\s*versionName:\s*'?([0-9.]+)'?\s*$",
                      y.read_text(encoding="utf-8", errors="replace"), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def report_version(root: Path, family: str) -> str:
    """Print the real base version and flag anything we have not been run on."""
    actual = apktool_version(root)
    if actual is None:
        print(f"Detected GameHub base version: {family} (family probe; "
              f"apktool.yml unreadable)")
        return family
    note = "" if actual in SUPPORTED_BASES else "  [UNTESTED on this base]"
    print(f"Detected GameHub base version: {actual} "
          f"({family}-family layout){note}")
    return actual



def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def write_lf(path: Path, content: str) -> None:
    # LF on every platform, matching apktool's own smali output.
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


# --- Bucket-agnostic locations for classes that keep their real names -------
# R8 shuffles dex buckets on nearly every build, and 6.3.0 went from 4 dex to 5,
# moving AndroidApp smali_classes2 -> smali_classes3. These keep their real
# package names, so discover the bucket rather than pinning it.
ANDROID_APP_REL = "com/xiaoji/egggame/AndroidApp.smali"
PLUGIN_HOST_REL = ("com/xiaoji/egggame/plugin/pcengine/host/"
                   "PcEnginePluginHostActivity.smali")


def find_in_any_bucket(root: Path, rel: str):
    """The one smali*/<rel>, or None."""
    hits = sorted(Path(root).glob(f"smali*/{rel}"))
    return hits[0] if len(hits) == 1 else None


def android_app_smali(root: Path) -> Path:
    p = find_in_any_bucket(root, ANDROID_APP_REL)
    if p is None:
        print(f"ERROR: {ANDROID_APP_REL} not found in any smali* bucket - the "
              f"Application class moved or was renamed; re-anchor.",
              file=sys.stderr)
        sys.exit(1)
    return p



# ---------------------------------------------------------------------------
# Version detection (mirrors apply_menu_patches.py)
# ---------------------------------------------------------------------------

VERSION_PROBES = {"6.1.1": (ANDROID_APP_REL, PLUGIN_HOST_REL)}


def detect_version(root: Path) -> str:
    matches = [
        ver
        for ver, probes in VERSION_PROBES.items()
        if all(find_in_any_bucket(root, p) for p in probes)
    ]
    if not matches:
        print(
            "ERROR: could not detect GameHub version — none of the known "
            "smali layout probes matched.",
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


# ---------------------------------------------------------------------------
# App-start hook
# ---------------------------------------------------------------------------

# The line stock onCreate() runs right after super.onCreate(); the register it
# stores is the Application. Holder class + field name are R8 letters (wildcarded,
# see the module docstring); the AndroidApp type name is what anchors us.
ONCREATE_ANCHOR_RE = re.compile(
    r"[ \t]*sput-object (v\d+), L[\w$/]+;->\w+:"
    r"Lcom/xiaoji/egggame/AndroidApp;\n"
)
# How many such stores stock onCreate has had (6.1.1 and 6.1.2 both: 2).
EXPECTED_APP_STORES = 2

def start_call(reg: str) -> str:
    """Our injected call, using whichever register the anchor stored from."""
    return (
        "\n"
        "    # BH: start the background Steam update-badge checker (once per\n"
        f"    # process). {reg} is the Application (a Context); super.onCreate has\n"
        "    # run. start() is itself gated to the main process.\n"
        f"    invoke-static {{{reg}}}, "
        "Lcom/xj/winemu/update/BhSteamUpdateChecker;->"
        "start(Landroid/content/Context;)V\n"
    )


def patch_app_start(root: Path) -> None:
    p = android_app_smali(root)
    src = read(p)

    if "Lcom/xj/winemu/update/BhSteamUpdateChecker;->start(" in src:
        print("OK: BhSteamUpdateChecker.start already injected")
        return

    hits = list(ONCREATE_ANCHOR_RE.finditer(src))
    if not hits:
        print(
            "ERROR: no static store of the AndroidApp instance found in "
            "AndroidApp.smali:\n"
            "  sput-object vN, L<holder>;-><field>:Lcom/xiaoji/egggame/AndroidApp;\n"
            "  (Application class or its onCreate layout changed — re-anchor.)",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(hits) != EXPECTED_APP_STORES:
        print(
            f"ERROR: expected {EXPECTED_APP_STORES} static AndroidApp stores in "
            f"onCreate, found {len(hits)}:\n"
            + "\n".join(f"  {h.group(0).strip()}" for h in hits)
            + "\n  onCreate's layout changed — confirm which store still follows "
            "super.onCreate() before shifting this anchor.",
            file=sys.stderr,
        )
        sys.exit(1)

    m = hits[0]                      # the one directly after super.onCreate()
    reg = m.group(1)
    print(f"    anchored on {m.group(0).strip()}  (register {reg})")
    src = src[:m.end()] + start_call(reg) + src[m.end():]
    write_lf(p, src)
    print("OK: AndroidApp.onCreate: start BhSteamUpdateChecker")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(2)

    version = detect_version(root)
    version = report_version(root, version)
    print()

    print("=== Background Steam update-badge checker ===")
    patch_app_start(root)
    print()

    print("Update-check patch applied successfully.")


if __name__ == "__main__":
    main()
