#!/usr/bin/env python3
"""
Patch Wine's winebus.so so SDL rumble starts do not expire after the short
duration Wine passes through from the guest force-feedback path. Both
aarch64-unix and x86_64-unix backends are supported; the script auto-detects
the architecture from ELF e_machine.

GameHub's Wine build calls SDL_JoystickRumble and SDL_JoystickRumbleTriggers
from sdl_device_haptics_start(). On aarch64 the stock code emits at each
call site:

    ldur w3, [x29, #-0x14]       ; load duration_ms into w3 (4th arg)
    blr  x8                      ; indirect call

We replace the load with `mov w3, #-1` so the 4th argument becomes
0xffffffff (~50 days), defeating SDL2's internal rumble auto-expiry.

On x86_64 (System V ABI) the same logic loads duration_ms into ECX (4th
arg). In the clang/NDK-r26 build shipped with wine_proton9.0-x64-3 the
compiler loads the function pointer into RAX first, then sets up args and
issues `call *%rax`. Each call site is an 11-byte window:

    8B 4D <disp8>     mov   ecx, DWORD PTR [rbp+disp8]   ; duration_ms
    0F B7 F6          movzwl %si, %esi                    ; 2nd arg fixup
    0F B7 D2          movzwl %dx, %edx                    ; 3rd arg fixup
    FF D0             call  *%rax

10 of 11 bytes fixed; only the disp8 floats. The movzwl pair discriminates
this from the haptics_stop call site (which uses xor/mov-reg-to-reg for
the same args and so doesn't match). We replace the first 3 bytes with
`or ecx, -1` (83 C9 FF) so ECX becomes 0xFFFFFFFF; the rest of the window
is preserved so the indirect call is untouched.

Two matches expected (rumble + rumble triggers); 0 or >2 hits is treated
as ambiguous and skipped to avoid a destructive miss.

Zero-duration stop paths are separate call sites and remain untouched on
both architectures.
"""
import argparse
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# aarch64
# ---------------------------------------------------------------------------

AARCH64_ORIGINAL_DURATION_LOAD = bytes.fromhex("a3 c3 5e b8")  # ldur w3, [x29, #-0x14]
AARCH64_INDIRECT_CALL_X8       = bytes.fromhex("00 01 3f d6")  # blr x8
AARCH64_PATCHED_DURATION_LOAD  = bytes.fromhex("03 00 80 12")  # mov w3, #-1

AARCH64_ORIGINAL_SITE = AARCH64_ORIGINAL_DURATION_LOAD + AARCH64_INDIRECT_CALL_X8
AARCH64_PATCHED_SITE  = AARCH64_PATCHED_DURATION_LOAD + AARCH64_INDIRECT_CALL_X8


# ---------------------------------------------------------------------------
# x86_64 — wildcards represented as (bytes, mask) where mask byte 0xff means
# "must match" and 0x00 means "wildcard".
#
# 11-byte window:
#   mov ecx, [rbp+disp8] ; movzwl si,esi ; movzwl dx,edx ; call *%rax
# Only the disp8 floats. Replace bytes 0..2 with `or ecx, -1` (83 C9 FF).
# ---------------------------------------------------------------------------

X86_64_PATTERN = (
    bytes.fromhex("8b 4d 00  0f b7 f6  0f b7 d2  ff d0"),
    bytes.fromhex("ff ff 00  ff ff ff  ff ff ff  ff ff"),
)
X86_64_PATCHED_PATTERN = bytes.fromhex("83 c9 ff  0f b7 f6  0f b7 d2  ff d0")
X86_64_PATCHED_LOAD = bytes.fromhex("83 c9 ff")


ELF_MACHINE_AARCH64 = 0xb7
ELF_MACHINE_X86_64  = 0x3e


def elf_machine(blob: bytes) -> int:
    return int.from_bytes(blob[18:20], "little")


def find_all(blob: bytes, needle: bytes) -> list[int]:
    hits = []
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1


def find_all_masked(blob: bytes, pattern: bytes, mask: bytes) -> list[int]:
    assert len(pattern) == len(mask)
    n = len(pattern)
    hits = []
    for i in range(len(blob) - n + 1):
        ok = True
        for j in range(n):
            if mask[j] and blob[i + j] != pattern[j]:
                ok = False
                break
        if ok:
            hits.append(i)
    return hits


def winebus_targets(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("winebus.so"))
    raise FileNotFoundError(path)


def patch_aarch64(path: Path, blob: bytes, *, dry_run: bool) -> bool:
    original_hits = find_all(blob, AARCH64_ORIGINAL_SITE)
    patched_hits = find_all(blob, AARCH64_PATCHED_SITE)

    if not original_hits:
        if len(patched_hits) == 2:
            print(f"OK: {path} already patched (aarch64) at "
                  f"{', '.join(hex(x) for x in patched_hits)}")
            return False
        raise ValueError(
            f"{path}: expected 2 original aarch64 rumble call sites, "
            f"found 0 original and {len(patched_hits)} patched"
        )

    if len(original_hits) != 2:
        raise ValueError(
            f"{path}: expected exactly 2 original aarch64 rumble call sites, "
            f"found {len(original_hits)} at {', '.join(hex(x) for x in original_hits)}"
        )

    print(f"PATCH (aarch64): {path}")
    for off in original_hits:
        print(f"  file+{off:#x}: ldur w3, [x29, #-0x14] -> mov w3, #-1")

    if dry_run:
        return True

    mutable = bytearray(blob)
    for off in original_hits:
        mutable[off:off + len(AARCH64_PATCHED_DURATION_LOAD)] = AARCH64_PATCHED_DURATION_LOAD
    path.write_bytes(mutable)

    verify = path.read_bytes()
    if find_all(verify, AARCH64_ORIGINAL_SITE) or len(find_all(verify, AARCH64_PATCHED_SITE)) != 2:
        raise RuntimeError(f"{path}: aarch64 verification failed after write")
    return True


def patch_x86_64(path: Path, blob: bytes, *, dry_run: bool) -> bool:
    hits = find_all_masked(blob, *X86_64_PATTERN)
    patched_hits = find_all(blob, X86_64_PATCHED_PATTERN)

    if not hits:
        if len(patched_hits) == 2:
            print(f"OK: {path} already patched (x86_64) at "
                  f"{', '.join(hex(x) for x in patched_hits)}")
            return False
        raise ValueError(
            f"{path}: expected 2 original x86_64 rumble call sites, "
            f"found 0 original and {len(patched_hits)} patched"
        )
    if len(hits) != 2:
        raise ValueError(
            f"{path}: expected exactly 2 original x86_64 rumble call sites, "
            f"found {len(hits)} at {', '.join(hex(x) for x in hits)}"
        )

    print(f"PATCH (x86_64): {path}")
    for off in hits:
        print(f"  file+{off:#x}: mov ecx, [rbp+disp8] -> or ecx, -1")

    if dry_run:
        return True

    mutable = bytearray(blob)
    for off in hits:
        mutable[off:off + len(X86_64_PATCHED_LOAD)] = X86_64_PATCHED_LOAD
    path.write_bytes(mutable)

    verify = path.read_bytes()
    if find_all_masked(verify, *X86_64_PATTERN) or len(find_all(verify, X86_64_PATCHED_PATTERN)) != 2:
        raise RuntimeError(f"{path}: x86_64 verification failed after write")
    return True


def patch_one(path: Path, *, backup: bool, dry_run: bool) -> bool:
    blob = path.read_bytes()
    if not blob.startswith(b"\x7fELF"):
        raise ValueError(f"{path}: not an ELF file")
    if b"SDL_JoystickRumble" not in blob:
        raise ValueError(f"{path}: SDL_JoystickRumble string not found")

    machine = elf_machine(blob)
    if not dry_run and backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
            print(f"  backup: {backup_path}")

    if machine == ELF_MACHINE_AARCH64:
        return patch_aarch64(path, blob, dry_run=dry_run)
    if machine == ELF_MACHINE_X86_64:
        return patch_x86_64(path, blob, dry_run=dry_run)
    raise ValueError(f"{path}: unsupported e_machine=0x{machine:x}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="winebus.so file(s), or directories to search recursively",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="write a .bak copy beside each modified winebus.so",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print patch sites without writing",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    for path in args.paths:
        targets.extend(winebus_targets(path))
    targets = sorted(set(targets))
    if not targets:
        print("ERROR: no winebus.so targets found", file=sys.stderr)
        return 1

    changed = 0
    try:
        for target in targets:
            changed += int(patch_one(target, backup=args.backup, dry_run=args.dry_run))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    action = "would change" if args.dry_run else "changed"
    print(f"Done: {action} {changed} of {len(targets)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
