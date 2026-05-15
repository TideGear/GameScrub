#!/usr/bin/env python3
"""
Patch Wine's aarch64-unix winebus.so so SDL rumble starts do not expire after
the short duration Wine passes through from the guest force-feedback path.

GameHub's Wine build calls SDL_JoystickRumble and SDL_JoystickRumbleTriggers
from sdl_device_haptics_start(). The stock code loads duration_ms into w3
immediately before each indirect SDL call:

    ldur w3, [x29, #-0x14]
    blr  x8

This script replaces those two loads with:

    mov  w3, #-1
    blr  x8

Zero-duration stop paths are separate call sites and remain untouched.
"""
import argparse
import shutil
import sys
from pathlib import Path


ORIGINAL_DURATION_LOAD = bytes.fromhex("a3 c3 5e b8")  # ldur w3, [x29, #-0x14]
INDIRECT_CALL_X8 = bytes.fromhex("00 01 3f d6")        # blr x8
PATCHED_DURATION_LOAD = bytes.fromhex("03 00 80 12")   # mov w3, #-1

ORIGINAL_SITE = ORIGINAL_DURATION_LOAD + INDIRECT_CALL_X8
PATCHED_SITE = PATCHED_DURATION_LOAD + INDIRECT_CALL_X8


def find_all(blob: bytes, needle: bytes) -> list[int]:
    hits = []
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1


def winebus_targets(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("winebus.so"))
    raise FileNotFoundError(path)


def patch_one(path: Path, *, backup: bool, dry_run: bool) -> bool:
    blob = path.read_bytes()
    if not blob.startswith(b"\x7fELF"):
        raise ValueError(f"{path}: not an ELF file")
    if b"SDL_JoystickRumble" not in blob:
        raise ValueError(f"{path}: SDL_JoystickRumble string not found")

    original_hits = find_all(blob, ORIGINAL_SITE)
    patched_hits = find_all(blob, PATCHED_SITE)

    if not original_hits:
        if len(patched_hits) == 2:
            print(f"OK: {path} already patched at "
                  f"{', '.join(hex(x) for x in patched_hits)}")
            return False
        raise ValueError(
            f"{path}: expected 2 original rumble duration call sites, "
            f"found 0 original and {len(patched_hits)} patched"
        )

    if len(original_hits) != 2:
        raise ValueError(
            f"{path}: expected exactly 2 original rumble duration call sites, "
            f"found {len(original_hits)} at {', '.join(hex(x) for x in original_hits)}"
        )

    print(f"PATCH: {path}")
    for off in original_hits:
        print(f"  file+{off:#x}: ldur w3, [x29, #-0x14] -> mov w3, #-1")

    if dry_run:
        return True

    if backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
            print(f"  backup: {backup_path}")

    mutable = bytearray(blob)
    for off in original_hits:
        mutable[off:off + len(PATCHED_DURATION_LOAD)] = PATCHED_DURATION_LOAD
    path.write_bytes(mutable)

    verify = path.read_bytes()
    verify_original = find_all(verify, ORIGINAL_SITE)
    verify_patched = find_all(verify, PATCHED_SITE)
    if verify_original or len(verify_patched) != 2:
        raise RuntimeError(
            f"{path}: verification failed after write "
            f"(original={len(verify_original)}, patched={len(verify_patched)})"
        )
    return True


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
