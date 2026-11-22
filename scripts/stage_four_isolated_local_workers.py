#!/usr/bin/env python3
"""Safely stage four additional one-job Chrome/worker lanes on the SAME VPS.

Does not change the controller or existing Chrome/worker. Does not read or print
session content, credentials or recordings. Preserves original rollback path.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path("/opt/beonmeet")
PREFIX = "beonmeet-isolated"
BASE_PROFILE = ROOT / "chrome-profile"
RUNTIME = ROOT / ".five-isolated-runtime"
STAGING = ROOT / ".five-isolated-in-progress"
CREATED_CONTAINERS = []
CREATED_PROFILES = []

def run(*args, quiet=False):
    proc = subprocess.run(args, text=True, capture_output=True, timeout=55)
    if proc.returncode:
        raise RuntimeError("command failed: " + " ".join(args[:4]) +
                           " code=" + str(proc.returncode) +
                           " stderr=" + proc.stderr[:250].replace("\n", " "))
    return proc.stdout.strip()

def docker_inspect(name):
    return json.loads(run("docker", "inspect", name))[0]

def get_json(url):
    with urllib.request.urlopen(url, timeout=7) as res:
        return json.load(res)

def capacity(port):
    data = get_json(f"http://127.0.0.1:{port}/capacity")
    return data.get("data") or data

def assert_host_idle():
    health = get_json("http://127.0.0.1:8109/health")
    assert health.get("ok")
    assert int(health.get("max_concurrent_meetings") or 0) == 5
    for key in ("free_queue", "premium_queue", "active_delivery_jobs", "pending_delivery_jobs"):
        assert int(health.get(key) or 0) == 0, "Production work exists: " + key
    for port in (9124, 9126):
        assert int(capacity(port).get("runningJobs") or 0) == 0, "Live recording is active"
    assert (os.cpu_count() or 0) >= 7
    available_kib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                             if line.startswith("MemAvailable:")))
    assert available_kib > 14 * 1024 * 1024
    assert shutil.disk_usage("/").free > 20 * 1024**3
    assert shutil.disk_usage("/dev/shm").free > 7 * 1024**3
    for container in ("camcam-shared-api-1","camcam-shared-pet-1",
                      "camcam-shared-archive-1","camcam-shared-petarchive-1"):
        assert run("docker", "inspect", "-f", "{{.State.Health.Status}}", container) == "healthy"
    print("FIVE_ISOLATED_PRECHECK_IDLE_AND_HEALTHY", flush=True)

def clone_profile(source, target):
    # No shared writable profile. Copy the authenticated Chrome state and
    # use sqlite's online backup for the cookie database if present.
    def ignore(_directory, names):
        return {name for name in names if name.startswith("Singleton") or name in {
            "LOCK", "GPUCache", "ShaderCache", "GrShaderCache", "Crashpad"}}
    shutil.copytree(source, target, symlinks=True, ignore=ignore)
    CREATED_PROFILES.append(target)
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        db = source / rel
        if not db.is_file():
            continue
        out = target / rel
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10) as src:
            with sqlite3.connect(out, timeout=10) as dst:
                src.backup(dst, pages=64, sleep=.05)
    for directory, subdirs, files in os.walk(target, followlinks=False):
        os.chown(directory, 1001, 1001)
        for item in files:
            obj = Path(directory) / item
            if not obj.is_symlink():
                os.chown(obj, 1001, 1001)
    target.chmod(0o700)

def start_container(name, args):
    assert name not in [x["Names"] for x in []]
    proc = subprocess.run(["docker", "run", "-d", "--name", name] + args,
                          capture_output=True, text=True, timeout=55)
    if proc.returncode:
        raise RuntimeError("Docker failed starting " + name + " (exit " + str(proc.returncode) +
                           "; no existing containers changed)")
    CREATED_CONTAINERS.append(name)

def wait_for(predicate, label, retries=35):
    for attempt in range(retries):
        try:
            if predicate():
                print("FIVE_ISOLATED_READY", label, flush=True)
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("Not ready: " + label)

def main():
    assert_host_idle()
    assert BASE_PROFILE.is_dir()
    assert not RUNTIME.exists() and not STAGING.exists(), "Previous staged environment exists"
    names = set(run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines())
    for i in range(2,6):
        assert (PREFIX + f"-chrome-{i}") not in names
        assert (PREFIX + f"-worker-{i}") not in names
        assert not (ROOT / f"chrome-profile-isolated-{i}").exists()
    original = docker_inspect("beonmeet-worker-five")
    assert original["State"]["Running"]
    overlay = next((m["Source"] for m in original["Mounts"]
                    if m["Destination"] == "/usr/src/app/dist/bots/GoogleMeetBot.js"), None)
    assert overlay and Path(overlay).is_file(), "Patched production recorder overlay missing"
    source = Path(overlay).read_text()
    for marker in ("BEONMEET_BROWSER_QUALITY_ARG_V1",
                   "BEONMEET_MODERN_IN_CALL_PROOF_V1"):
        assert marker in source, "Recorder production patch not found: " + marker

    STAGING.mkdir(mode=0o700)
    original_env = original["Config"]["Env"]
    for i in range(2,6):
        env_lines = [line for line in original_env
                     if not line.startswith(("MAX_CONCURRENT_MEETINGS=", "GOOGLE_CHROME_CDP_URL="))]
        assert all("\n" not in line and "\r" not in line for line in env_lines)
        env_lines.extend(["MAX_CONCURRENT_MEETINGS=1",
                          f"GOOGLE_CHROME_CDP_URL=http://{PREFIX}-chrome-{i}:9223"])
        for required in ("INTERNAL_SECRET=", "REDIS_HOST=", "CONTROLLER_UPLOAD_URL="):
            assert any(line.startswith(required) for line in env_lines), "Missing worker setting"
        env_file = STAGING / f"worker-{i}.env"
        env_file.write_text("\n".join(env_lines) + "\n")
        env_file.chmod(0o600)

    for i in range(2,6):
        profile = ROOT / f"chrome-profile-isolated-{i}"
        clone_profile(BASE_PROFILE, profile)
        name = PREFIX + f"-chrome-{i}"
        start_container(name, [
            "--network", "beonmeet-single", "--restart", "unless-stopped",
            "--memory=1800m", "--memory-swap=2100m", "--cpus=1.15",
            "--pids-limit=450", "--shm-size=512m",
            "-e", "CHROME_WINDOW_SIZE=1280,720",
            "-v", f"{profile}:/tmp/chrome-profile",
            "-p", f"127.0.0.1:{6180+i}:6080",
            "beonmeet-chrome-cdp:latest"
        ])
        wait_for(lambda: subprocess.run(
            ["docker", "exec", name, "curl", "-fsS", "--max-time", "2",
             "http://127.0.0.1:9223/json/version"],
            capture_output=True, timeout=5).returncode == 0, name, 45)
        assert_host_idle()

    for i in range(2,6):
        name = PREFIX + f"-worker-{i}"
        start_container(name, [
            "--network", "beonmeet-single", "--restart", "unless-stopped",
            "--memory=1100m", "--memory-swap=1350m", "--cpus=.65",
            "--pids-limit=350", "--shm-size=256m",
            "-p", f"127.0.0.1:{9130+i}:3000",
            "--env-file", str(STAGING / f"worker-{i}.env"),
            "-v", "/dev/shm/beonmeet:/recordings",
            "-v", f"{overlay}:/usr/src/app/dist/bots/GoogleMeetBot.js:ro",
            "beonmeet-worker-audiofix:latest"
        ])
        wait_for(lambda: int(capacity(9130+i).get("availableSlots") or 0) == 1,
                 name)
        c = capacity(9130+i)
        assert int(c.get("maxConcurrentJobs") or 0) == 1
        assert int(c.get("runningJobs") or 0) == 0
        actual = docker_inspect(name)
        env = dict(line.split("=",1) for line in actual["Config"]["Env"] if "=" in line)
        assert env["GOOGLE_CHROME_CDP_URL"] == f"http://{PREFIX}-chrome-{i}:9223"
        print("FIVE_ISOLATED_WORKER_ONE_SLOT_VERIFIED",i,flush=True)
        assert_host_idle()

    assert_host_idle()
    STAGING.rename(RUNTIME)
    print("FIVE_ISOLATED_FOUR_STANDBY_LANES_STAGED_SUCCESS",flush=True)
    print("FIVE_ISOLATED_CONTROLLER_NOT_CHANGED",flush=True)

if __name__ == "__main__":
    lock_path = Path("/var/lock/pars-vds-bot-deploy.lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            main()
        except Exception as exc:
            print("FIVE_ISOLATED_STAGING_FAILED",type(exc).__name__,str(exc)[:280],flush=True)
            for name in reversed(CREATED_CONTAINERS):
                subprocess.run(["docker","rm","-f",name], capture_output=True,timeout=25)
            for directory in reversed(CREATED_PROFILES):
                shutil.rmtree(directory, ignore_errors=True)
            if STAGING.exists():shutil.rmtree(STAGING,ignore_errors=True)
            print("FIVE_ISOLATED_ROLLED_BACK_NEW_CONTAINERS_ONLY",flush=True)
            sys.exit(1)
