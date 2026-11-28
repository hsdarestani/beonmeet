#!/usr/bin/env python3
"""Stage and apply BeOnMeet controller/watchdog changes without restarting recorders."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path("/opt/beonmeet")
BASE_RELEASE = "e6d408949c59066ced7ed5219ef16aa6013185ff"
SERVICE = "beonmeet-controller"
TIMER = "beonmeet-auth-watch.timer"
WATCH = "beonmeet-auth-watch.service"
FILES = ("app/main.py", "app/admin_panel.py", "scripts/worker_auth_monitor.py", "scripts/probe_recorder_auth.js")
PORTS = (9124, 9126, 9132, 9133, 9134, 9135)


def run(*command, timeout=30):
    return subprocess.run(command, cwd=ROOT, timeout=timeout, check=True, capture_output=True).stdout


def get(port, endpoint):
    with urlopen(f"http://127.0.0.1:{port}/{endpoint}", timeout=5) as response:
        result = json.load(response)
    return result.get("data") or result


def ensure_idle():
    health = get(8109, "health")
    if not health.get("ok") or not health.get("auth_guard_enabled"):
        raise RuntimeError("Current controller or auth guard is unhealthy")
    if any(health.get(key) for key in ("free_queue", "premium_queue", "active_delivery_jobs", "pending_delivery_jobs")):
        raise RuntimeError("Controller has queued work or an active delivery")
    if any(int(get(port, "capacity")["runningJobs"]) for port in PORTS):
        raise RuntimeError("A recorder is busy")


def atomic_copy(source, destination):
    fd, name = tempfile.mkstemp(prefix=".reliability-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        info = source.stat()
        os.chown(temporary, info.st_uid, info.st_gid)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def stage(release, directory):
    for filename in FILES:
        live = ROOT / filename
        saved = directory / (Path(filename).name + ".before")
        staged = directory / Path(filename).name
        shutil.copy2(live, saved)
        current_stat = live.stat()
        os.chown(saved, current_stat.st_uid, current_stat.st_gid)
        proposed = run("git", "show", f"{release}:{filename}")
        if filename.startswith("app/"):
            previous = directory / (live.name + ".base")
            changed = directory / (live.name + ".proposed")
            previous.write_bytes(run("git", "show", f"{BASE_RELEASE}:{filename}"))
            changed.write_bytes(proposed)
            result = subprocess.run(["git", "merge-file", "-p", str(saved), str(previous), str(changed)],
                                    check=False, capture_output=True, timeout=20)
            if result.returncode:
                raise RuntimeError("Production source merge needs review for " + filename)
            proposed = result.stdout
        staged.write_bytes(proposed)
        shutil.copystat(live, staged)
        os.chown(staged, current_stat.st_uid, current_stat.st_gid)
        if live.suffix == ".py":
            compile(proposed, filename, "exec")
        else:
            run("docker", "exec", "beonmeet-worker-five", "node", "--version")
            with staged.open("rb") as stream:
                subprocess.run(["docker", "exec", "-i", "beonmeet-worker-five", "node", "--check"],
                               stdin=stream, check=True, capture_output=True, timeout=15)
    print("RELIABILITY_MERGED_SOURCE_VALIDATED", release, flush=True)


def wait_for_health():
    for _ in range(20):
        try:
            if get(8109, "health").get("ok"):
                return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Controller did not become healthy")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release")
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()
    if run("git", "rev-parse", args.release).decode().strip() != args.release:
        raise RuntimeError("Expected a pinned release SHA")
    with tempfile.TemporaryDirectory(prefix=".recording-reliability-stage-", dir=ROOT) as path:
        staging = Path(path)
        stage(args.release, staging)
        if args.stage_only:
            return

        ensure_idle()
        backup = Path(tempfile.mkdtemp(prefix=".recording-reliability-backup-", dir=ROOT))
        settings = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                        if "=" in line and not line.startswith("#"))
        readiness = Path(settings.get("WORKER_AUTH_STATE_FILE") or str(ROOT / "data/worker-auth-readiness.json"))
        if not readiness.resolve().is_relative_to(ROOT / "data"):
            raise RuntimeError("Unexpected production readiness location")
        for file in [*FILES, str(readiness.relative_to(ROOT)), "data/state.json"]:
            src = ROOT / file
            dst = backup / src.name
            shutil.copy2(src, dst)
            os.chown(dst, src.stat().st_uid, src.stat().st_gid)

        controller_changed = False
        run("systemctl", "stop", TIMER)
        try:
            # The old controller also respects readiness. Stop new joins while
            # existing dispatch calls settle, then recheck each physical slot.
            hold = staging / "readiness-hold.json"
            hold.write_text('{"workers": {}}\n')
            shutil.copystat(readiness, hold)
            os.chown(hold, readiness.stat().st_uid, readiness.stat().st_gid)
            atomic_copy(hold, readiness)
            time.sleep(34)
            ensure_idle()
            for filename in FILES:
                atomic_copy(staging / Path(filename).name, ROOT / filename)
            controller_changed = True
            run("systemctl", "restart", SERVICE)
            wait_for_health()
            try:
                with urlopen("http://127.0.0.1:8109/admin/recorder-health", timeout=5):
                    raise RuntimeError("Admin recorder status is unexpectedly public")
            except HTTPError as exc:
                if exc.code != 401:
                    raise
        except Exception:
            for filename in FILES:
                atomic_copy(backup / Path(filename).name, ROOT / filename)
            if controller_changed:
                run("systemctl", "restart", SERVICE)
                wait_for_health()
            raise
        finally:
            atomic_copy(backup / readiness.name, readiness)
            run("systemctl", "start", TIMER)
        print("RELIABILITY_CONTROLLER_DEPLOYED", args.release,
              hashlib.sha256((ROOT / "app/main.py").read_bytes()).hexdigest(), flush=True)


if __name__ == "__main__":
    main()
