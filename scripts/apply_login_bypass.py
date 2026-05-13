#!/usr/bin/env python3
"""
Apply login-bypass patches to a decompiled GameHub apktool tree.
Supports stock 6.0.2 and 6.0.4.

Effect: make the app's "is logged in" gate report true unconditionally
so the launcher Activity proceeds straight to the home screen instead
of routing through the login screen, and short-circuit the
SharedPreferences read for "app_agreement_agreed" so the splash's
privacy-policy popup never fires.

Mechanism (6.0.x)
-----------------
The "is logged in" state is a Compose StateFlow<Boolean> exposed by
the auth state holder `Lit0;` (field `c`, returned by `it0.h()`). The
StateFlow is derived from a combine() of two upstream flows:

    user  = userDao.observeCurrentUser()  -> StateFlow<UserEntity?>
    token = authTokenDao.observeCurrent() -> StateFlow<AuthTokenEntity?>
    isLoggedIn = combine(user, token) { u, t -> u != null && t != null }

The combine lambda (extends SuspendLambda, implements Function3) has
its `invokeSuspend()` rewritten to always return `Boolean.TRUE`, which
makes every downstream observer (including the Compose start-
destination selector that picks home-vs-login) see the user as
authenticated.

Separately, the splash screen reads `app_agreement_agreed` from
SharedPreferences via a thin wrapper class with `e(String, Z)Z`. We
patch the wrapper to short-circuit that one key to `true`; all other
keys fall through to the original `getBoolean()` logic, so unrelated
boolean prefs are untouched.

Locator strategy — by signature, not by class name
--------------------------------------------------
Both the auth-state combiner and the preference wrapper are
R8-obfuscated to two- or three-letter class names that shift between
minor 6.0.x releases (e.g. 6.0.2 `dt0`/`dyj`, 6.0.4 `et0`/`kyj`).
Rather than hardcode names, we scan `smali_classes4/` for the
distinctive signatures and bail with a clear error if zero or more
than one class matches.
"""
import re
import sys
from pathlib import Path


# Method body the bypass replaces — common across both invokeSuspend
# variants found in the wild (R8 may emit `.locals 1` or `.locals 2`).
BYPASS_METHOD = """.method public final invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;
    .locals 1

    # BH: login bypass — force isLoggedIn = true unconditionally.
    # Replaces the original `user != null && token != null` combiner
    # in the auth state holder's StateFlow derivation. Every consumer
    # of the resulting StateFlow now sees the user as authenticated,
    # which makes the launcher's start-destination selector pick the
    # home screen instead of the login screen.
    const/4 v0, 0x1
    invoke-static {v0}, Ljava/lang/Boolean;->valueOf(Z)Ljava/lang/Boolean;
    move-result-object v0
    return-object v0
.end method"""


METHOD_RE = re.compile(
    r'\.method public final invokeSuspend\(Ljava/lang/Object;\)Ljava/lang/Object;'
    r'.*?\.end method',
    re.DOTALL,
)


def looks_like_auth_combiner(path: Path) -> bool:
    """A 2-input combine lambda has L$0 + L$1 synthetic fields and an
    invokeSuspend that ANDs them and boxes to Boolean. Must be a
    straight-line method (no suspend state machine) — that's what
    distinguishes the auth combiner from larger combine lambdas that
    happen to share the L$0+L$1 field layout (e.g. media-focus
    combiners with .locals 44 and many iput-object L$0 writes for
    resumption state)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    if ".field synthetic L$0:Ljava/lang/Object;" not in text:
        return False
    if ".field synthetic L$1:Ljava/lang/Object;" not in text:
        return False
    m = METHOD_RE.search(text)
    if not m:
        return False
    body = m.group(0)
    # Required: both null-checks + a Boolean boxing.
    if "if-eqz v0, :cond_" not in body:
        return False
    if "if-eqz v1, :cond_" not in body:
        return False
    if body.count("Ljava/lang/Boolean;->valueOf(Z)Ljava/lang/Boolean;") != 1:
        return False
    # Reject state-machine-laden combines: those write the suspended
    # state into L$0/L$1 inside invokeSuspend before yielding. The
    # auth combiner never suspends so it never does these writes.
    if "L$0:Ljava/lang/Object;\n" in body and "iput-object" in body \
            and re.search(r"iput-object\s+\S+,\s+\S+,\s+L\S+;->L\$[01]:", body):
        return False
    # Auth combiner has a small register budget (.locals 2 in 6.0.2);
    # >4 reliably indicates a state-machine combine.
    locals_m = re.search(r"\.locals\s+(\d+)", body)
    if locals_m and int(locals_m.group(1)) > 4:
        return False
    # Auth combiner body is ~1.3 KB; >2 KB indicates a state machine.
    if len(body) > 2048:
        return False
    return True


def detect_version(root: Path) -> str:
    """Match the same probe set used by apply_vibration_patches.py."""
    if (root / "smali_classes3/za8.smali").is_file() \
            and (root / "smali_classes3/dg5.smali").is_file():
        return "6.0.2"
    if (root / "smali_classes3/ab8.smali").is_file() \
            and (root / "smali_classes3/bg5.smali").is_file():
        return "6.0.4"
    return "unknown"


def find_auth_combiner_6x(root: Path) -> Path:
    """Scan smali_classes4 for the single auth-state combiner lambda.

    The class is in smali_classes4 on stock 6.0.2 (it's co-located with
    the auth state holder `it0` in stock Tencent's R8 output). Walking
    only classes4 keeps the scan fast and avoids matching unrelated
    2-arg combine lambdas elsewhere (image-loading combines, etc., that
    happen to share the L$0+L$1 field layout).
    """
    candidates = []
    classes4 = root / "smali_classes4"
    if not classes4.is_dir():
        print(f"ERROR: {classes4} not found", file=sys.stderr)
        sys.exit(1)
    for smali in classes4.glob("*.smali"):
        if looks_like_auth_combiner(smali):
            candidates.append(smali)
    if not candidates:
        print(
            "ERROR: no auth-state combiner lambda found in smali_classes4/.\n"
            "Stock GameHub's auth-state observer should expose a 2-arg "
            "combine lambda with L$0+L$1 synthetic fields and an "
            "invokeSuspend that returns Boolean.valueOf(user!=null && token!=null). "
            "Either the smali layout has shifted in this base version, or "
            "this isn't a GameHub apktool tree.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(candidates) > 1:
        print(
            "ERROR: multiple auth-combiner candidates found, refusing to "
            "guess which one is the right login gate:",
            file=sys.stderr,
        )
        for c in candidates:
            print(f"  {c}", file=sys.stderr)
        print(
            "\nNarrow the signature check in looks_like_auth_combiner() "
            "before re-running.",
            file=sys.stderr,
        )
        sys.exit(1)
    return candidates[0]


def patch_6x(root: Path) -> None:
    target = find_auth_combiner_6x(root)
    print(f"Found auth-combiner: {target.relative_to(root)}")
    src = target.read_text(encoding="utf-8")
    m = METHOD_RE.search(src)
    if not m:
        print(f"ERROR: invokeSuspend method vanished from {target}", file=sys.stderr)
        sys.exit(1)
    out = src[:m.start()] + BYPASS_METHOD + src[m.end():]
    target.write_text(out, encoding="utf-8")
    print(f"OK: rewrote {target.name}.invokeSuspend -> return Boolean.TRUE")


# ---------------------------------------------------------------------------
# Privacy-policy popup bypass (6.0.x)
# ---------------------------------------------------------------------------
#
# Login bypass alone is not enough on 6.0.2: the splash screen still pops a
# Compose modal titled "Privacy Policy" with body "Welcome to GameHub! …"
# before reaching the launcher, and tapping Disagree quits the app. The
# strings live in the features.splash compose-resource pool under keys
# `features_splash_privacy_dialog_*` (base64-encoded values).
#
# Gating mechanism:
#   * Splash ViewModel (obfuscated class `chk` on stock 6.0.2; extends
#     androidx.lifecycle.ViewModel via `Lod1;`) holds a SharedPreferences
#     wrapper at field `i:Lii0;`.
#   * The wrapper is `Ldyj;` — a thin SharedPreferences proxy whose
#     `e(String, boolean)Z` is a `getBoolean(key, default)` accessor:
#       method body =
#         contains(key) ? getBoolean(key, default) : default
#   * The splash dispatches an Agreement event via `chk.m(Lxgk;)V` which
#     reads `dyj.e("app_agreement_agreed", false)` to decide what to do
#     next. If the dialog hasn't been shown / agreed to yet, the splash
#     model has dialogVisible=true and the Compose pipeline renders the
#     modal. Once the user taps Agree, the agreement event is fired and
#     the flag is persisted; subsequent launches return early.
#
# Bypass: intercept the getBoolean wrapper. When the key parameter equals
# "app_agreement_agreed", short-circuit and return true. All other keys
# fall through to the original logic, so we don't affect any unrelated
# boolean preference.
#
# Locator strategy — by signature, not class name:
#   * The wrapper implements interface `Lii0;` (same interface the
#     splash ViewModel's `i` field uses) — but matching by interface
#     name is fragile since `ii0` is itself R8-obfuscated.
#   * Instead, scan smali_classes4 for any class whose `e(String, Z)Z`
#     method body matches the exact getBoolean-with-default shape:
#     `SharedPreferences.contains` then `SharedPreferences.getBoolean`,
#     no other side effects. Stock 6.0.2 has exactly one such class.

PRIVACY_KEY = "app_agreement_agreed"

GETBOOL_METHOD_RE = re.compile(
    r'\.method public final e\(Ljava/lang/String;Z\)Z'
    r'.*?\.end method',
    re.DOTALL,
)


def looks_like_pref_wrapper(path: Path) -> bool:
    """A SharedPreferences boolean-getter wrapper class:
    has e(String, Z)Z whose body calls SharedPreferences.contains then
    SharedPreferences.getBoolean. Distinguishes from the splash
    ViewModel's `m`/`n`/`o` methods (different signatures) and from
    unrelated `e(String, Z)Z` methods that don't touch SharedPreferences."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    m = GETBOOL_METHOD_RE.search(text)
    if not m:
        return False
    body = m.group(0)
    if "Landroid/content/SharedPreferences;->contains(Ljava/lang/String;)Z" not in body:
        return False
    if "Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z" not in body:
        return False
    # Should also have the trio of sibling methods that the SharedPref
    # wrapper class typically exposes (string + int getters/setters).
    # This narrows the match: the auth-state holder doesn't have these.
    if ".method public final f(ILjava/lang/String;)I" not in text:
        return False
    if ".method public final g(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;" not in text:
        return False
    return True


def find_pref_wrapper_6x(root: Path) -> Path:
    """Stock 6.0.2 has the SharedPreferences wrapper in smali_classes4.
    Scan that dir for the single class matching the wrapper signature."""
    candidates = []
    classes4 = root / "smali_classes4"
    if not classes4.is_dir():
        print(f"ERROR: {classes4} not found", file=sys.stderr)
        sys.exit(1)
    for smali in classes4.glob("*.smali"):
        if looks_like_pref_wrapper(smali):
            candidates.append(smali)
    if not candidates:
        print(
            "ERROR: no SharedPreferences boolean-wrapper class found in "
            "smali_classes4/. Privacy bypass cannot proceed without it. "
            "If stock GameHub's preference layer has been refactored this "
            "may need an updated heuristic.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(candidates) > 1:
        print(
            "ERROR: multiple SharedPreferences wrapper candidates — "
            "refusing to guess which one is the privacy-flag gate:",
            file=sys.stderr,
        )
        for c in candidates:
            print(f"  {c}", file=sys.stderr)
        sys.exit(1)
    return candidates[0]


def patch_6x_privacy(root: Path) -> None:
    target = find_pref_wrapper_6x(root)
    print(f"Found preference wrapper: {target.relative_to(root)}")
    src = target.read_text(encoding="utf-8")
    m = GETBOOL_METHOD_RE.search(src)
    if not m:
        print(f"ERROR: e(String,Z)Z method vanished from {target}", file=sys.stderr)
        sys.exit(1)
    original_body = m.group(0)

    # Pull the original .locals N out so we can preserve it. We need at
    # least 1 free register; the original uses .locals 1 (v0). Our
    # intercept reuses v0 for the comparison string then for the equals
    # result, so .locals 1 is fine.
    locals_m = re.search(r"\.locals\s+(\d+)", original_body)
    original_locals = int(locals_m.group(1)) if locals_m else 1
    new_locals = max(original_locals, 1)

    # Inject a prefix block that returns Boolean true when the requested
    # key matches PRIVACY_KEY, otherwise falls through to the stock body.
    # Smali rewriting strategy: replace the method declaration line and
    # inject the intercept right after .locals, before the original body.
    method_header_re = re.compile(
        r'(\.method public final e\(Ljava/lang/String;Z\)Z\n'
        r'\s*\.locals\s+\d+\n)',
    )
    intercept = (
        f"    # BH: privacy popup bypass - short-circuit the\n"
        f"    # \"{PRIVACY_KEY}\" key to true so the splash screen's\n"
        f"    # Compose dialog never gates on first launch. All other\n"
        f"    # keys fall through to the original getBoolean logic.\n"
        f"    const-string v0, \"{PRIVACY_KEY}\"\n"
        f"    invoke-virtual {{p1, v0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n"
        f"    move-result v0\n"
        f"    if-eqz v0, :bh_privacy_fallthrough\n"
        f"    const/4 p0, 0x1\n"
        f"    return p0\n"
        f"    :bh_privacy_fallthrough\n\n"
    )
    new_body = method_header_re.sub(
        lambda m: m.group(1).replace(
            f".locals {original_locals}",
            f".locals {new_locals}",
        ) + intercept,
        original_body,
        count=1,
    )
    if new_body == original_body:
        print("ERROR: failed to inject privacy intercept (header regex miss)", file=sys.stderr)
        sys.exit(1)
    out = src[:m.start()] + new_body + src[m.end():]
    target.write_text(out, encoding="utf-8")
    print(
        f"OK: injected privacy intercept in {target.name}.e(String,Z)Z -> "
        f"return true when key == \"{PRIVACY_KEY}\""
    )


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
    if version in ("6.0.2", "6.0.4"):
        patch_6x(root)
        patch_6x_privacy(root)
    else:
        print(
            f"ERROR: don't know how to bypass login on version '{version}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nLogin bypass applied successfully.")


if __name__ == "__main__":
    main()
