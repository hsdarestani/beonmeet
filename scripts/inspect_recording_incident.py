#!/usr/bin/env python3
"""Read production evidence without exposing meeting URLs, customers, or credentials."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
from urllib.request import urlopen

ROOT = Path("/opt/beonmeet")
SINCE = "2026-11-28T13:00:00+00:00"
UNTIL = "2026-11-28T13:35:00+00:00"
WORKERS = {9126: "beonmeet-worker-five", **{
    9130 + lane: f"beonmeet-isolated-worker-{lane}" for lane in range(2, 6)
}}
SIGNATURES = {
    "prejoin_timeout": r"pre-join controls.*not ready|waiting for.*pre-join.*timeout",
    "browser_disconnected": r"browser has been closed|browser.*disconnect|target closed",
    "capture_stream_failed": r"failed to get media stream|error starting recording|notreadableerror",
    "chunk_persistence_failed": r"recording chunk persistence failed|unable to write recording chunk",
    "chunk_bridge_failed": r"error uploading chunk|recording chunk deadline exceeded",
    "callback_rejected": r"controller rejected capture state|recording-start callback failed",
    "callback_config_missing": r"recording controller is unavailable",
    "finalization_timeout": r"mediarecorder stop deadline|recording flush deadline",
    "handoff_failed": r"beonmeet delivery failed|controller returned|recording source missing",
    "media_invalid": r"invalid media|recording has no|unprocessable recording",
    "delivery_failed": r"pending delivery recovery error|telegram.*(?:failed|error)",
}
HTTP_ROUTE = re.compile(r'(/internal/(?:waiting-for-admission|recording-started|recording-ready|recording-upload))[^"\s]* HTTP/\d\.\d"\s+(\d{3})')


def report(label, value):
    print(label, json.dumps(value, sort_keys=True), flush=True)


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=25).stdout


def get(port, path):
    with urlopen(f"http://127.0.0.1:{port}/{path}", timeout=6) as response:
        data = json.load(response)
    return data.get("data") or data


def error_summary(log):
    codes = Counter(f"{route}:{status}" for route, status in HTTP_ROUTE.findall(log))
    errors = {key: len(re.findall(pattern, log, flags=re.IGNORECASE))
              for key, pattern in SIGNATURES.items()}
    return {"http": dict(codes), "errors": {key: n for key, n in errors.items() if n}}


def main():
    state = json.loads((ROOT / "data/state.json").read_text())
    readiness = json.loads((ROOT / "data/worker-auth-readiness.json").read_text())
    current = datetime.now(timezone.utc).timestamp()
    report("CONTROLLER_SOURCE", hashlib.sha256((ROOT / "app/main.py").read_bytes()).hexdigest())
    for port, worker in WORKERS.items():
        row = readiness.get("workers", {}).get(f"http://127.0.0.1:{port}", {})
        cap = get(port, "capacity")
        inspect = json.loads(command("docker", "inspect", worker))[0]
        config = dict(entry.split("=", 1) for entry in inspect["Config"]["Env"] if "=" in entry)
        report("LANE", {
            "port": port, "running": cap.get("runningJobs"),
            "reported_ready": row.get("ready"), "proof_age": round(current - float(row.get("checked_at") or 0)),
            "restarts": inspect["RestartCount"], "oom": inspect["State"]["OOMKilled"],
            "start_callback_configured": bool(config.get("CONTROLLER_RECORDING_STARTED_URL")),
            "stream_upload_configured": bool(config.get("CONTROLLER_STREAM_UPLOAD_URL")),
            "local_upload_configured": bool(config.get("CONTROLLER_UPLOAD_URL")),
            "shared_recording_mount": any(m["Destination"] == config.get("RECORDING_TMP_DIR", "/recordings")
                                          for m in inspect["Mounts"]),
        })
        logs = subprocess.run(["docker", "logs", "--since", SINCE, "--until", UNTIL, worker],
                              check=True, capture_output=True, text=True, timeout=25)
        report("LANE_ERRORS", {"port": port, **error_summary(logs.stdout + "\n" + logs.stderr)})

    log = command("journalctl", "-u", "beonmeet-controller", "--since", "2026-11-28 13:00 UTC",
                  "--until", "2026-11-28 13:35 UTC", "--no-pager")
    report("CONTROLLER_ERRORS", error_summary(log))
    for group in ("launched_events", "failed_recordings", "pending_deliveries", "completed_deliveries"):
        entries = state.get(group, {})
        report("STATE", {"group": group, "count": len(entries),
                         "status_counts": dict(Counter(str(row.get("status", "no_status"))
                                                     for row in entries.values() if isinstance(row, dict)))})
    report("HEALTH", {key: value for key, value in get(8109, "health").items() if key in {
        "ok", "healthy_free_workers", "authenticated_free_workers", "active_recording_jobs",
        "failed_recording_jobs", "active_delivery_jobs", "pending_delivery_jobs", "pending_transcription_jobs",
    }})


if __name__ == "__main__":
    main()
