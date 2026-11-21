#!/usr/bin/env python3
"""Safely self-heal BeOnMeet's shared Chrome CDP bridge while all jobs are idle.

The existing health endpoint checks HTTP, which can stay healthy while
Playwright's WebSocket/DevTools connection is hung. This watchdog probes an
actual Playwright CDP handshake without creating pages, requires two failed
probes, and only restarts the dedicated Chrome container while all BeOnMeet
recorders and delivery queues are idle. It never touches CamCam.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

STATE_PATH = Path("/run/beonmeet-chrome-cdp-watchdog.json")
LOCK_PATH = Path("/var/lock/pars-vds-bot-deploy.lock")
CHROME_CONTAINER = "beonmeet-chrome-single"
WORKER_CONTAINER = "beonmeet-worker-five"
CAPACITY_PORTS = (9124, 9126)
COOLDOWN_SECONDS = 30 * 60
CAMCAM_CONTAINERS = (
    "camcam-shared-api-1",
    "camcam-shared-pet-1",
    "camcam-shared-archive-1",
    "camcam-shared-petarchive-1",
)

# Deliberately connect without creating a tab or closing the shared browser.
# Exiting this Node client closes only its own remote protocol connection.
PLAYWRIGHT_PROBE_JS = r"""
(async () => {
  const timer = setTimeout(() => process.exit(7), 14500);
  try {
    const { chromium } = require('playwright-extra');
    const url = process.env.GOOGLE_CHROME_CDP_URL;
    if (!url) process.exit(8);
    await chromium.connectOverCDP(url, { timeout: 11500 });
    clearTimeout(timer);
    process.exit(0);
  } catch (_) {
    clearTimeout(timer);
    process.exit(9);
  }
})();
"""


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _json_from_url(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.load(response)
    return data.get("data", data)


def work_is_idle() -> bool:
    """Fail closed if any endpoint is unreachable or a recording may be active."""
    try:
        controller = _json_from_url("http://127.0.0.1:8109/health")
        if not controller.get("ok"):
            return False
        for key in ("free_queue", "premium_queue", "active_delivery_jobs", "pending_delivery_jobs"):
            if int(controller.get(key) or 0):
                return False
        for port in CAPACITY_PORTS:
            worker = _json_from_url(f"http://127.0.0.1:{port}/capacity")
            if int(worker.get("runningJobs") or 0):
                return False
        return True
    except Exception:
        return False


def neighbors_healthy() -> bool:
    try:
        for name in CAMCAM_CONTAINERS:
            p = _run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name], 8)
            if p.returncode != 0 or p.stdout.strip() != "healthy":
                return False
        return True
    except Exception:
        return False


def probe_cdp() -> bool:
    try:
        p = _run(["docker", "exec", WORKER_CONTAINER, "node", "-e", PLAYWRIGHT_PROBE_JS], 21)
        return p.returncode == 0
    except Exception:
        return False


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    return {"failures": 0, "last_restart": 0}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, sort_keys=True))
    os.chmod(temp, 0o600)
    temp.replace(STATE_PATH)


def should_recover(state: dict[str, Any], now: float) -> bool:
    return (
        int(state.get("failures") or 0) >= 2
        and now - float(state.get("last_restart") or 0) >= COOLDOWN_SECONDS
    )


def main() -> int:
    if os.geteuid() != 0:
        print("CDP_WATCHDOG_SKIP_NONROOT")
        return 1
    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("CDP_WATCHDOG_SKIP_MAINTENANCE_LOCK")
            return 0
        if not work_is_idle():
            print("CDP_WATCHDOG_SKIP_ACTIVE_OR_UNKNOWN_JOBS")
            return 0

        state = load_state()
        if probe_cdp():
            if state.get("failures"):
                print("CDP_WATCHDOG_PROBE_RECOVERED")
            save_state({"failures": 0, "last_restart": state.get("last_restart", 0)})
            print("CDP_WATCHDOG_PLAYWRIGHT_HEALTHY")
            return 0

        state["failures"] = min(100, int(state.get("failures") or 0) + 1)
        print("CDP_WATCHDOG_PROBE_FAILED", state["failures"])
        if not should_recover(state, time.time()):
            save_state(state)
            return 0

        # Recheck immediately: a new job may have arrived since the first probe.
        if not work_is_idle() or not neighbors_healthy():
            save_state(state)
            print("CDP_WATCHDOG_RESTART_SKIPPED_SAFETY")
            return 0

        state["last_restart"] = time.time()
        state["failures"] = 0
        save_state(state)  # cooldown applies even if Docker restart fails
        try:
            p = _run(["docker", "restart", "--time", "20", CHROME_CONTAINER], 60)
            if p.returncode != 0:
                print("CDP_WATCHDOG_RESTART_FAILED")
                return 1
            print("CDP_WATCHDOG_CHROME_RESTARTED_IDLE")
            for _ in range(6):
                time.sleep(4)
                if not work_is_idle():  # don't probe while a new join is running
                    print("CDP_WATCHDOG_POSTCHECK_SKIPPED_ACTIVE")
                    return 0
                if probe_cdp():
                    print("CDP_WATCHDOG_RECOVERY_CONFIRMED")
                    return 0
            print("CDP_WATCHDOG_RECOVERY_NOT_CONFIRMED")
            return 1
        except Exception as exc:
            print("CDP_WATCHDOG_RECOVERY_ERROR_CLASS", type(exc).__name__)
            return 1


if __name__ == "__main__":
    sys.exit(main())
