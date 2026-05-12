#!/usr/bin/env python3
"""
Apply login-bypass patches to a decompiled GameHub apktool tree.
Supports stock 5.3.5 and 6.0.2.

Effect: make the app's "is logged in" gate report true unconditionally
so the launcher Activity proceeds straight to the home screen instead
of routing through the login screen. The privacy-policy text in
stock GameHub lives inline on the login screen footer (there is no
separate first-launch privacy dialog in 5.3.5 / 6.0.2), so bypassing
the login screen also takes the privacy popup with it.

6.0.2 mechanism
---------------
The "is logged in" state is a Compose StateFlow<Boolean> exposed by
the auth state holder `Lit0;` (field `c`, returned by `it0.h()`). The
StateFlow is derived from a combine() of two upstream flows:

    user  = userDao.observeCurrentUser()  -> StateFlow<UserEntity?>
    token = authTokenDao.observeCurrent() -> StateFlow<AuthTokenEntity?>
    isLoggedIn = combine(user, token) { u, t -> u != null && t != null }

The combine lambda is class `Ldt0;` (extends SuspendLambda, implements
Function3). Its `invokeSuspend()` returns `Boolean.valueOf(user != null
&& token != null)`. We rewrite the body to always return
`Boolean.TRUE`, which makes every downstream observer (including the
Compose start-destination selector that picks home-vs-login) see the
user as authenticated.

Locator strategy — by signature, not by class name
--------------------------------------------------
The class name `dt0` is R8-obfuscated and shifts between minor
6.0.x releases. Rather than hardcode it, we scan all `smali_classes4/`
files for a class that has:
  - Two synthetic instance fields `L$0:Ljava/lang/Object;` and
    `L$1:Ljava/lang/Object;` (the captured args of a 2-input combine
    lambda).
  - A NON-suspending `invokeSuspend()` body: it must do its
    null-checks + Boolean boxing in a single straight-line block.
    Concretely: exactly one `Boolean.valueOf(Z)` call, no
    `iput-object …, …, L$[01]:` writes inside invokeSuspend (writes
    indicate state-machine resumption, which the simple auth
    combiner doesn't need), and a tight `.locals` budget (≤4).
  - Body length under ~2 KB — auth combiner is ~1.3 KB. Larger
    matches are state-machine-laden combine lambdas elsewhere
    (e.g. media-focus combiners that capture many fields).
This signature is distinctive enough that exactly one class matches
on stock 6.0.2 (the auth-state combiner). If zero or more than one
match, the script bails out with a clear error rather than guessing.

5.3.5 mechanism
---------------
Auth state is held by a non-obfuscated Kotlin singleton at a fixed
path (`Lcom/xj/common/user/UserManager;` under
`smali_classes8/com/xj/common/user/`). Five method-body replacements
do the bypass: `isLogin()Z` always returns true, and `getUid` /
`getUsername` / `getNickname` / `getAvatar` return synthetic
constants so any consumer reading them gets benign values instead
of empties from a never-completed login. Approach lifted from
playday3008/gamehub-patches PR #13.

Usage:
    python3 apply_login_bypass.py <apktool_decompile_dir>

Fails fast: exits non-zero if the bypass target can't be unambiguously
identified.
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
    if (root / "smali_classes7/com/winemu/core/gamepad/GamepadDevice$Physical.smali").is_file():
        return "5.3.5"
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


# ---------------------------------------------------------------------------
# 5.3.5 login bypass
# ---------------------------------------------------------------------------
#
# Unlike 6.0.x, 5.3.5 ships UserManager with un-obfuscated symbols at a
# fixed path. The class is a Kotlin singleton with public-final getters
# (isLogin, getUid, getUsername, getNickname, getAvatar, getToken, ...).
# Every gate across the app routes through `UserManager.isLogin()Z` and
# the launcher's start destination is selected from it; replacing the
# body to `return true` makes the gate accept the user as signed-in and
# skips the login screen entirely (Google sign-in / email verification
# code / etc. — none of those flows ever execute).
#
# The other four getters are stubbed to synthetic values so any UI code
# that reads them while the dialog/profile sheet is open gets benign
# strings/integers instead of empty values that could trip downstream
# null/length checks.
#
# Approach lifted from playday3008/gamehub-patches PR #13's
# BypassLoginPatch. We do five method-body replacements on
# Lcom/xj/common/user/UserManager; — find each by exact-signature regex
# in a single text pass, replace, write back.

UM_PATH = "smali_classes8/com/xj/common/user/UserManager.smali"

# Each entry: (method signature line, new full method body). Smali
# `.locals 1` is enough for every replacement — they all just load one
# constant and return.
USERMANAGER_PATCHES = {
    "isLogin()Z": """.method public final isLogin()Z
    .locals 1

    # BH: login bypass - always report logged-in so the launcher
    # skips the login Activity. Replaces stock body that checked
    # `getToken().length > 0 && getUid() >= 0`.
    const/4 v0, 0x1
    return v0
.end method""",
    "getUid()I": """.method public final getUid()I
    .locals 1

    # BH: login bypass - synthetic uid (large positive constant so
    # `getUid() >= 0` checks pass everywhere).
    const v0, 0x1869f
    return v0
.end method""",
    "getUsername()Ljava/lang/String;": """.method public final getUsername()Ljava/lang/String;
    .locals 1

    # BH: login bypass - synthetic username.
    const-string v0, "Local"
    return-object v0
.end method""",
    "getNickname()Ljava/lang/String;": """.method public final getNickname()Ljava/lang/String;
    .locals 1

    # BH: login bypass - synthetic display name.
    const-string v0, "Local Player"
    return-object v0
.end method""",
    "getAvatar()Ljava/lang/String;": """.method public final getAvatar()Ljava/lang/String;
    .locals 1

    # BH: login bypass - empty avatar URL. UI falls back to a
    # default avatar drawable when this is empty.
    const-string v0, ""
    return-object v0
.end method""",
}


def patch_535(root: Path) -> None:
    """5.3.5 login bypass has two halves:

    1) Replace 5 UserManager getters with synthetic constants so the
       launcher's startup gate sees the user as logged-in (skips
       GuideLoginActivity).
    2) Bypass the guide-step validator (RouterUtils.checkGuideStep$1
       + RouterUtils.n / .z) so the post-login privacy popup +
       create-avatar wizard + periodic session-validity recheck are
       all short-circuited. Without (2) the app reaches home briefly,
       then `checkGuideStep` fires, the synthetic session fails the
       server-side validation, and RouterUtils.z routes back to login
       with the "Your session has expired" toast.

    Lift from playday3008/gamehub-patches PR #13's BypassLoginPatch +
    bypassTokenExpiryPatch.
    """
    target = root / UM_PATH
    if not target.is_file():
        print(
            f"ERROR: UserManager not found at {UM_PATH}. Is this really a "
            "stock 5.3.5 apktool tree?",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Found UserManager: {target.relative_to(root)}")

    src = target.read_text(encoding="utf-8")
    out = src
    for sig, new_body in USERMANAGER_PATCHES.items():
        method_re = re.compile(
            r'\.method public final '
            + re.escape(sig)
            + r'\n.*?\.end method',
            re.DOTALL,
        )
        m = method_re.search(out)
        if not m:
            print(
                f"ERROR: method `public final {sig}` not found in {target.name} "
                "(stock signature may have shifted between minor 5.3.5 builds)",
                file=sys.stderr,
            )
            sys.exit(1)
        out = out[:m.start()] + new_body + out[m.end():]
        print(f"OK: rewrote UserManager.{sig} -> synthetic constant")

    target.write_text(out, encoding="utf-8")

    patch_535_guide_bypass(root)


# ---------------------------------------------------------------------------
# 5.3.5 guide-step / token-expiry bypass
# ---------------------------------------------------------------------------

ROUTER_UTILS_PATH = "smali_classes8/com/xj/landscape/launcher/router/RouterUtils.smali"
CHECK_GUIDE_PATH = "smali_classes8/com/xj/landscape/launcher/router/RouterUtils$checkGuideStep$1.smali"

# n()V and z()V both early-return with no side effects. n() is the
# debounced "schedule a guide-step recheck"; z() is the activity-stack
# clear + relaunch GuideLoginActivity routine. With both stubbed out,
# the periodic recheck timer never fires and the session-expired
# branch (when reached) never restarts the login Activity.
ROUTER_NOOP_METHODS = {
    "n()V": """.method public n()V
    .locals 0

    # BH: login bypass - no-op the guide-step recheck timer entry so
    # the synthetic session is never re-validated against the server.
    return-void
.end method""",
    "z()V": """.method public final z()V
    .locals 0

    # BH: login bypass - no-op the relaunch-to-login routine so a
    # 401 anywhere never kicks the user back to GuideLoginActivity.
    return-void
.end method""",
}


def patch_535_guide_bypass(root: Path) -> None:
    # 1. Stub n() and z() on RouterUtils.
    ru = root / ROUTER_UTILS_PATH
    if not ru.is_file():
        print(
            f"ERROR: RouterUtils not found at {ROUTER_UTILS_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Found RouterUtils: {ru.relative_to(root)}")
    src = ru.read_text(encoding="utf-8")
    out = src
    for sig, new_body in ROUTER_NOOP_METHODS.items():
        # Match `.method public[ final] <sig>` so the regex picks up
        # whichever modifiers stock uses (n() is `public`, z() is
        # `public final`).
        method_re = re.compile(
            r'\.method public(?: final)? '
            + re.escape(sig)
            + r'\n.*?\.end method',
            re.DOTALL,
        )
        m = method_re.search(out)
        if not m:
            print(
                f"ERROR: method `public[ final] {sig}` not found in "
                f"{ru.name}",
                file=sys.stderr,
            )
            sys.exit(1)
        out = out[:m.start()] + new_body + out[m.end():]
        print(f"OK: stubbed RouterUtils.{sig} -> return-void")
    ru.write_text(out, encoding="utf-8")

    # 2. Replace the entire `checkGuideStep$1.invokeSuspend` body with
    # `return Unit.INSTANCE`. This is the suspend lambda that the
    # validator dispatches to; returning the Kotlin "completed
    # successfully with Unit" sentinel tells the coroutine machinery
    # "done, no work needed" and the caller proceeds to whatever
    # happens after the guide-step check (in stock 5.3.5, that's the
    # DeviceManager.A() check → home screen path).
    #
    # We use full-body replacement rather than injecting a `goto/16`
    # into the original body because the original is a state-machine
    # suspend function with many live registers of different types
    # (Ref$BooleanRef, Ref$ObjectRef, String, Integer, ...) at every
    # potential goto site, and the Dalvik verifier requires all
    # incoming paths to a label to agree on register types. Two
    # previous attempts at goto injection both crashed with
    # `java.lang.VerifyError` (first on v4, then on v3) because the
    # post-injection control-flow merge violated those constraints.
    # Replacing the whole body is verifier-trivial: one method, one
    # straight-line return, no merge points.
    cg = root / CHECK_GUIDE_PATH
    if not cg.is_file():
        print(
            f"ERROR: checkGuideStep$1 not found at {CHECK_GUIDE_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Found checkGuideStep$1: {cg.relative_to(root)}")
    src = cg.read_text(encoding="utf-8")

    new_invoke_suspend = (
        '.method public final invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;\n'
        '    .locals 1\n'
        '\n'
        '    # BH: login bypass - return Unit unconditionally. This\n'
        '    # short-circuits the guide-step validator coroutine so\n'
        '    # the privacy popup, avatar wizard, and 401-driven\n'
        '    # session-expired redirect never fire. Caller treats\n'
        '    # the return as "validation complete" and falls through\n'
        '    # to the DeviceManager.A() / home-screen path.\n'
        '    sget-object v0, Lkotlin/Unit;->INSTANCE:Lkotlin/Unit;\n'
        '    return-object v0\n'
        '.end method'
    )
    method_re = re.compile(
        r'\.method public final invokeSuspend\(Ljava/lang/Object;\)Ljava/lang/Object;'
        r'.*?\.end method',
        re.DOTALL,
    )
    m = method_re.search(src)
    if not m:
        print(
            f"ERROR: invokeSuspend method not found in {cg.name}.",
            file=sys.stderr,
        )
        sys.exit(1)
    src = src[:m.start()] + new_invoke_suspend + src[m.end():]
    cg.write_text(src, encoding="utf-8")
    print(
        "OK: rewrote checkGuideStep$1.invokeSuspend -> return Unit.INSTANCE"
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
    if version == "6.0.2":
        patch_6x(root)
        patch_6x_privacy(root)
    elif version == "5.3.5":
        patch_535(root)
    else:
        print(
            f"ERROR: don't know how to bypass login on version '{version}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nLogin bypass applied successfully.")


if __name__ == "__main__":
    main()
