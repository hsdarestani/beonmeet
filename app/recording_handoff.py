"""Durable disk handoff helpers; deliberately independent of Telegram and STT."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def recording_key(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()


def persist_source(source: Path, destination: Path) -> None:
    """Publish a complete copy atomically; never publish a partial recording."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".incoming-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if not temporary.stat().st_size:
            raise ValueError("Empty recording")
        os.replace(temporary, destination)
        fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def verified_duration(path: Path) -> int:
    """Require both actual media streams and positive duration before billing."""
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-count_packets", "-show_entries",
        "format=duration:stream=codec_type,nb_read_packets,duration", "-of", "json", str(path),
    ], check=True, capture_output=True, text=True, timeout=180)
    metadata = json.loads(probe.stdout)
    streams = metadata.get("streams", [])
    present = {s.get("codec_type") for s in streams if str(s.get("nb_read_packets", "")).isdigit() and int(s["nb_read_packets"]) > 0}
    if not {"video", "audio"}.issubset(present):
        raise ValueError("Recording lacks audio or video packets")
    durations = [metadata.get("format", {}).get("duration"), *(s.get("duration") for s in streams)]
    usable = []
    for value in durations:
        try:
            n = float(value)
            if math.isfinite(n) and n > 0:
                usable.append(n)
        except (ValueError, TypeError):
            pass
    if not usable:
        # Live MediaRecorder WebM files can lack container duration. Read the
        # media timestamps by remuxing to the null output, without re-encoding.
        result = subprocess.run([
            "ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-f", "null", "-",
        ], check=True, capture_output=True, text=True, timeout=180)
        usable = [int(line.split("=", 1)[1]) / 1_000_000 for line in result.stdout.splitlines()
                  if line.startswith("out_time_us=") and line.split("=", 1)[1].isdigit()]
    if not usable or max(usable) <= 0:
        raise ValueError("Recording duration cannot be verified")
    return max(1, math.ceil(max(usable)))
