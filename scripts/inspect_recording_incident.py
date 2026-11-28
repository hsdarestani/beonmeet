#!/usr/bin/env python3
"""Read production evidence without exposing meeting URLs, customers, or credentials."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import stat
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


def tracebacks(log):
    frames = re.findall(r'File "[^"\n]*/(?:app/)?(main|recording_handoff|state_store)\.py", line (\d+), in (\w+)', log)
    report("CONTROLLER_FRAMES", dict(Counter(f"{file}:{name}:{line}" for file, line, name in frames)))
    errors = re.findall(r"(?:^|\s)([A-Z][A-Za-z]*(?:Error|Exception)):", log)
    report("ERROR_CLASSES", dict(Counter(errors)))
    codes = re.findall(r"\[Errno (\d+)\]", log)
    report("OS_ERROR_NUMBERS", dict(Counter(codes)))
    names = re.findall(r"NameError: name '(persist_source|recording_key|verified_duration|RECORDING_SPOOL)' is not defined", log)
    report("MISSING_RECORDING_SYMBOLS", dict(Counter(names)))


def inspect_capture_files(state):
    settings = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                    if "=" in line and not line.startswith("#"))
    recording_root = Path(settings.get("RECORDING_TMP_DIR", "/recordings")).resolve()
    spool = ROOT / "data/recording-spool"
    owner = (ROOT / "app/main.py").stat()
    pid = int(command("systemctl", "show", "beonmeet-controller", "--property=MainPID", "--value"))
    proc = {key: value.split() for key, value in
            (line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line)}
    credentials = {"uid": int(proc["Uid"][1]), "gid": int(proc["Gid"][1]),
                   "groups": [int(value) for value in proc.get("Groups", [])]}
    report("CONTROLLER_CREDENTIALS", credentials)
    lines = (ROOT / "app/main.py").read_text().splitlines()
    report("HANDOFF_3979", next((label for label, expression in {
        "stat_source": "source.is_file()", "copy_source": "persist_source",
        "resolve_source": "source.resolve()", "validate_source": "assert_recording_path",
    }.items() if expression in lines[3978]), "other"))
    report("RECONCILE_ERRORS", dict(Counter(re.findall(r"recording reconciliation error: (\w+)",
        command("journalctl", "-u", "beonmeet-controller", "--since", "2026-11-28 13:00 UTC", "--no-pager")))))
    report("STORAGE_LAYOUT", {"recording_root_exists": recording_root.is_dir(),
                              "spool_exists": spool.is_dir(),
                              "spool_owner": spool.stat().st_uid if spool.is_dir() else None,
                              "source_owner": owner.st_uid})
    component = lambda value: re.sub(r"[^a-zA-Z0-9_-]", "_", value)
    for index, (eid, job) in enumerate(sorted(state.get("launched_events", {}).items(),
                                                   key=lambda row: row[1].get("launched_at", "")), 1):
        if job.get("launched_at", "") < SINCE or job.get("launched_at", "") > UNTIL:
            continue
        folder = recording_root / component(str(job.get("chat_id") or "")) / component(eid)
        files = [f for f in folder.iterdir() if f.is_file() and not f.is_symlink()] if folder.is_dir() else []
        spooled = list(spool.glob(hashlib.sha256(eid.encode()).hexdigest() + ".*"))
        def perms(path):
            data = path.stat()
            return [data.st_uid, data.st_gid, oct(stat.S_IMODE(data.st_mode))]
        if len(files) == 1:
            fp = files[0]
            with fp.open("rb") as f:
                f.read(1)
            probe = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                                    "format=duration:stream=codec_type,nb_read_packets", "-of", "json", str(fp)],
                                   capture_output=True, text=True, timeout=30)
            media = json.loads(probe.stdout or "{}")
            report("CAPTURE_AUTHORITY", {"number": index, "root": perms(recording_root),
                                         "user_dir": perms(folder.parent), "job_dir": perms(folder),
                                         "file": perms(fp), "probe_exit": probe.returncode,
                                         "streams": [[r.get("codec_type"), r.get("nb_read_packets")]
                                                     for r in media.get("streams", [])],
                                         "duration": media.get("format", {}).get("duration")})
        report("INCIDENT_JOB", {"number": index, "pool": job.get("pool"), "status": job.get("status"),
                                "exact_worker_files": len(files), "file_sizes": [f.stat().st_size for f in files],
                                "exact_spool_files": len(spooled), "has_capture_callback": bool(job.get("recording_started_at")),
                                "source_recovery_attempts": job.get("source_recovery_attempts", 0),
                                "idle_observed": bool(job.get("idle_observed_at"))})


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
    tracebacks(log)
    inspect_capture_files(state)
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
