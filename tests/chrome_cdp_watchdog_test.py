#!/usr/bin/env python3
"""CDP watchdog safety regression: busy jobs never get restarted."""
import importlib.util
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cdp_watchdog", ROOT / "scripts/chrome_cdp_watchdog.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

assert not watch.should_recover({"failures": 1, "last_restart": 0}, 5000)
assert not watch.should_recover({"failures": 2, "last_restart": 4900}, 5000)
assert watch.should_recover({"failures": 2, "last_restart": 0}, 5000)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    watch.STATE_PATH = root / "state.json"
    watch.LOCK_PATH = root / "maintenance.lock"
    watch.os.geteuid = lambda: 0
    watch.time.time = lambda: 5000
    watch.time.sleep = lambda _: None
    calls = {"restart": 0, "probe": 0}
    watch.work_is_idle = lambda: True
    watch.neighbors_healthy = lambda: True

    def probe():
        calls["probe"] += 1
        return calls["probe"] >= 3

    def run(args, timeout=20):
        if args[:2] == ["docker", "restart"]:
            calls["restart"] += 1
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    watch.probe_cdp = probe
    watch._run = run
    assert watch.main() == 0
    assert calls["restart"] == 0
    assert watch.load_state()["failures"] == 1

    assert watch.main() == 0
    assert calls["restart"] == 1
    assert calls["probe"] == 3
    assert watch.load_state()["failures"] == 0

    # A failed probe cannot restart inside the 30-minute cooldown.
    watch.probe_cdp = lambda: False
    assert watch.main() == 0
    assert watch.main() == 0
    assert calls["restart"] == 1

    # Active/unknown jobs suppress every CDP probe and restart.
    watch.work_is_idle = lambda: False
    before = calls["restart"]
    assert watch.main() == 0
    assert calls["restart"] == before

print("CHROME_CDP_WATCHDOG_IDLE_GUARD_AND_COOLDOWN_TEST_PASS")
