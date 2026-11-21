#!/usr/bin/env python3
"""Fail-closed overlay for the deployed compiled BeOnMeet DiskUploader.js.

Worker UID 1001 creates per-user folders under recording tmpfs. The systemd
controller UID 999 (shared group 987) must create MP3, remuxed MP4 and
transcript outputs in those folders; default 0755 blocks it. Correct mode
and repair any preexisting user directory each time a recording is accepted.
"""
import argparse
from pathlib import Path

OLD = "        await fs_1.default.promises.mkdir(instance.folderPath(), { recursive: true });"
NEW = """        await fs_1.default.promises.mkdir(instance.folderPath(), { recursive: true, mode: 0o2770 });
        await fs_1.default.promises.chmod(instance.folderPath(), 0o2770);"""


def patched_source(source: str) -> str:
    if source.count(OLD) != 1 or "await fs_1.default.promises.chmod(instance.folderPath(), 0o2770)" in source:
        raise ValueError("Compiled uploader version mismatch or already patched")
    return source.replace(OLD, NEW, 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("destination", type=Path)
    args = ap.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refuse in-place editing")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("UPLOADER_GROUP_WRITABLE_FOLDER_PATCH_READY")
