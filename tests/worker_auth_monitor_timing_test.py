#!/usr/bin/env python3
"""Exercise distinct probe verdicts, proof timing, and the dispatch lease."""
import fcntl
import importlib.util
import json
import pathlib
import tempfile
import types
from unittest.mock import patch

root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("watch", root / "scripts/worker_auth_monitor.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

with tempfile.TemporaryDirectory() as tmp:
    status = pathlib.Path(tmp) / "status.json"
    ports = watch.PORTS

    def key(port):
        return f"http://127.0.0.1:{port}"

    old = {key(port): {"ready": True, "checked_at": 800} for port in ports}
    status.write_text(json.dumps({"workers": old}))

    def capacity(port):
        if port == ports[0]:
            return {"runningJobs": 1, "availableSlots": 0}
        if port == ports[4]:
            return {}
        return {"runningJobs": 0, "availableSlots": 1}

    def probe(code, due):
        assert due == list(ports[1:4])
        with status.with_name(f"worker-auth-{ports[1]}.lock").open("rb") as descriptor:
            try:
                fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("A probe must exclude new dispatches on the same lane")
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"workers": {
            key(ports[1]): {"status": "verified", "reason": "meet_signed_in_prejoin", "checked_at": 995},
            key(ports[2]): {"status": "inconclusive", "reason": "fixture", "checked_at": 998},
            key(ports[3]): {"status": "reauthentication_required", "reason": "challenge", "checked_at": 999},
        }}))

    with (
        patch.object(watch, "config", return_value={"WORKER_AUTH_STATE_FILE": str(status)}),
        patch.object(watch, "capacity", side_effect=capacity),
        patch.object(watch, "run_node", side_effect=probe),
        patch.object(watch.time, "time", return_value=1000),
    ):
        watch.main()

    result = json.loads(status.read_text())["workers"]
    assert result[key(ports[0])]["status"] == "busy"
    assert result[key(ports[0])]["checked_at"] == 800
    assert result[key(ports[1])]["last_verified_at"] == 995
    assert result[key(ports[1])]["ready"] is True
    assert result[key(ports[2])]["last_verified_at"] == 800
    assert result[key(ports[2])]["status"] == "inconclusive"
    assert result[key(ports[2])]["ready"] is False
    assert result[key(ports[3])]["status"] == "reauthentication_required"
    assert result[key(ports[4])]["status"] == "unavailable"

    with (
        patch.object(watch, "config", return_value={"WORKER_AUTH_STATE_FILE": str(status)}),
        patch.object(watch, "capacity", return_value={"runningJobs": 0, "availableSlots": 1}),
        patch.object(watch, "run_node", return_value=types.SimpleNamespace(returncode=1, stdout="")),
        patch.object(watch.time, "time", return_value=1500),
    ):
        watch.main()
    result = json.loads(status.read_text())["workers"]
    assert all(row["status"] == "inconclusive" and not row["ready"] for row in result.values())

print("AUTH_WATCHDOG_IDLE_LEASE_VERDICTS_AND_PROOF_TIMESTAMPS_PASS")
