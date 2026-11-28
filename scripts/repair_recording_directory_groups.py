#!/usr/bin/env python3
"""Repair only BeOnMeet shared recording directory metadata, without restarts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from urllib.request import urlopen

ROOT = Path("/opt/beonmeet")
PORTS = (9124, 9126, 9132, 9133, 9134, 9135)
SHARED_GROUP = 987
RECORDER_UID = 1001
DIRECTORY = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY


@contextmanager
def open_directory(name, *, parent=None):
    descriptor = os.open(name, DIRECTORY, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def require_idle_workers():
    for port in PORTS:
        with urlopen(f"http://127.0.0.1:{port}/capacity", timeout=6) as response:
            data = json.load(response)
        if int((data.get("data") or data)["runningJobs"]) != 0:
            raise RuntimeError("Worker busy; defer recording-directory maintenance")


def repair(descriptor, path, backup_log):
    before = os.fstat(descriptor)
    if before.st_uid != RECORDER_UID:
        return False
    old_mode = stat.S_IMODE(before.st_mode)
    new_mode = old_mode | stat.S_ISGID | stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP
    if before.st_gid == SHARED_GROUP and new_mode == old_mode:
        return False
    backup_log.write(json.dumps({"path": str(path), "gid": before.st_gid, "mode": old_mode,
                                 "inode": before.st_ino, "device": before.st_dev}) + "\n")
    backup_log.flush()
    os.fsync(backup_log.fileno())
    if before.st_gid != SHARED_GROUP:
        os.fchown(descriptor, -1, SHARED_GROUP)
    os.fchmod(descriptor, new_mode)
    return True


def main():
    settings = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                    if "=" in line and not line.startswith("#"))
    capture_root = Path(settings["RECORDING_TMP_DIR"]).resolve(strict=True)
    if capture_root != Path("/dev/shm/beonmeet"):
        raise RuntimeError("Unexpected live recording mount")
    group = subprocess.check_output(
        ["systemctl", "show", "beonmeet-controller", "--property=Group", "--value"], text=True
    ).strip()
    import grp
    if not group or (int(group) if group.isdigit() else grp.getgrnam(group).gr_gid) != SHARED_GROUP:
        raise RuntimeError("Unexpected live controller group")
    require_idle_workers()
    state_path = ROOT / "data/state.json"
    state = json.loads(state_path.read_text())
    backup = Path(tempfile.mkdtemp(prefix=".recording-dir-metadata-", dir=ROOT))
    shutil.copyfile(state_path, backup / "controller-state.json")
    counters = {"capture_root": 0, "user_directories": 0, "known_job_directories": 0}
    with open_directory(capture_root) as root_fd, (backup / "changes.jsonl").open("x") as ledger:
        root_details = os.fstat(root_fd)
        if root_details.st_uid != RECORDER_UID or root_details.st_gid != SHARED_GROUP:
            raise RuntimeError("Unexpected shared recording mount ownership")
        counters["capture_root"] += repair(root_fd, capture_root, ledger)
        for user_dir in os.listdir(root_fd):
            if not re.fullmatch(r"-?\d+", user_dir):
                continue
            try:
                with open_directory(user_dir, parent=root_fd) as user_fd:
                    info = os.fstat(user_fd)
                    if info.st_gid == SHARED_GROUP and info.st_uid == RECORDER_UID:
                        counters["user_directories"] += repair(user_fd, capture_root / user_dir, ledger)
            except (FileNotFoundError, NotADirectoryError):
                continue
        for event_id, job in state.get("launched_events", {}).items():
            user_dir = str(job.get("chat_id") or "")
            if not re.fullmatch(r"-?\d+", user_dir) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", event_id):
                continue
            try:
                with open_directory(user_dir, parent=root_fd) as user_fd, open_directory(event_id, parent=user_fd) as job_fd:
                    counters["known_job_directories"] += repair(job_fd, capture_root / user_dir / event_id, ledger)
            except (FileNotFoundError, NotADirectoryError):
                continue
    print("RECORDING_DIRECTORY_PERMISSIONS_REPAIRED", json.dumps(counters), flush=True)


if __name__ == "__main__":
    main()
