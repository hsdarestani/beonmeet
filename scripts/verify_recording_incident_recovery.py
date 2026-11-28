#!/usr/bin/env python3
"""Verify recovered recordings and billing by original event and owner identifiers."""
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path("/opt/beonmeet")
STATE = ROOT / "data/state.json"
LOWER = "2026-11-28T13:00:00+00:00"
UPPER = "2026-11-28T13:35:00+00:00"


def main():
    backup = sorted(ROOT.glob(".recording-dir-metadata-*/controller-state.json"),
                    key=lambda path: path.stat().st_mtime)[-1]
    before = json.loads(backup.read_text())
    after = json.loads(STATE.read_text())
    settings = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                    if "=" in line and not line.startswith("#"))
    print("RECOVERY_CURRENT_CONTROLLER", hashlib.sha256((ROOT / "app/main.py").read_bytes()).hexdigest(), flush=True)
    db_path = Path(settings.get("BEONMEET_DB_PATH", str(ROOT / "data/beonmeet.db")))
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        rows = sorted(before["launched_events"].items(), key=lambda row: row[1].get("launched_at", ""))
        for position, (event_id, job) in enumerate(rows, 1):
            if not LOWER <= job.get("launched_at", "") <= UPPER:
                continue
            completed = after.get("completed_deliveries", {}).get(event_id, {})
            pending = after.get("pending_deliveries", {}).get(event_id, {})
            failed = after.get("failed_recordings", {}).get(event_id, {})
            live = after.get("launched_events", {}).get(event_id, {})
            delivery = completed or pending
            owner = str(job["chat_id"])
            name = delivery.get("filename")
            if delivery and str(delivery.get("chat_id")) != owner:
                raise RuntimeError("Unexpected recording owner")
            # Standard-sized free videos may change the extension during transcoding.
            names = (name, str(Path(name).with_suffix(".mp4"))) if name else ("", "")
            media = db.execute(
                "SELECT filename,duration_seconds FROM recordings WHERE telegram_id=? AND filename IN (?,?)",
                (owner, *names),
            ).fetchall()
            credits = db.execute(
                "SELECT seconds_delta FROM credit_entries WHERE telegram_id=? AND reference IN (?,?)",
                (owner, *(f"recording:{owner}:{value}" for value in names)),
            ).fetchall()
            print("RECOVERY_JOB", json.dumps({
                "position": position, "lane": job.get("pool"),
                "video_delivered": bool(completed or pending.get("video_delivered")),
                "audio_delivered": bool(completed or pending.get("audio_delivered")),
                "pipeline_complete": bool(completed),
                "failure_notice_sent": bool(failed.get("notified")),
                "stage": live.get("status"),
                "recording_rows": len(media),
                "duration_seconds": [row[1] for row in media],
                "wallet_debits_seconds": [-row[0] for row in credits],
            }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
