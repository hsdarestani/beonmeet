#!/usr/bin/env python3
"""Behavioral regression with five real local A/V files and one chat identity."""
import ast
import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from recording_handoff import persist_source, recording_key, verified_duration


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


async def test(root):
    capture = root / "capture"
    spool = root / "spool"
    capture.mkdir()
    spool.mkdir()
    sample = capture / "room.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "2",
                    "-c:v", "libvpx", "-c:a", "libopus", str(sample)], check=True)
    assert 2 <= verified_duration(sample) <= 3
    invalid = capture / "invalid.webm"
    invalid.write_bytes(b"not media")
    try:
        verified_duration(invalid)
    except (subprocess.CalledProcessError, ValueError):
        pass
    else:
        raise AssertionError("invalid recording must not be billed")

    ids = [f"job-{i}" for i in range(5)]
    launched = {eid: {"chat_id": "same-account", "meet_url": f"https://meet.google.com/{i}ab-cdef-ghi", "premium": True} for i, eid in enumerate(ids)}
    state = {"launched_events": launched, "pending_deliveries": {}, "completed_deliveries": {}, "failed_recordings": {}}
    saves = []

    async def save_state():
        saves.append(set(state["pending_deliveries"]))

    def check_path(path):
        assert path.is_relative_to(capture) or path.is_relative_to(spool)

    env = dict(Any=Any, Path=Path, asyncio=asyncio, state=state, HTTPException=HTTPException,
               normalize_meet_url=lambda x: x, delivery_locks={}, save_state=save_state,
               assert_recording_path=check_path, RECORDING_SPOOL=spool, recording_key=recording_key,
               persist_source=persist_source, datetime=datetime, timezone=timezone, timedelta=timedelta)
    tree = ast.parse((ROOT / "app/main.py").read_text())
    accept = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "accept_recording")
    exec(compile(ast.Module(body=[accept], type_ignores=[]), "main.py", "exec"), env)
    request = lambda eid: {"userId": "same-account", "botId": eid, "meetingLink": launched[eid]["meet_url"], "size": sample.stat().st_size}
    results = await asyncio.gather(*(env["accept_recording"](request(eid), sample) for eid in ids))
    assert all(result["persisted"] for result in results)
    assert len(saves[-1]) == 5
    pending = state["pending_deliveries"]
    assert len({job["file_path"] for job in pending.values()}) == 5
    assert len({job["filename"] for job in pending.values()}) == 5
    for eid in ids:
        assert Path(pending[eid]["file_path"]).read_bytes() == sample.read_bytes()
        assert pending[eid]["meeting_link"] == request(eid)["meetingLink"]
    # A retry must not wait for a long-running delivery of the same job.
    async with env["delivery_locks"][ids[0]]:
        result = await asyncio.wait_for(env["accept_recording"](request(ids[0]), sample), timeout=1)
        assert result["duplicate"]
    try:
        await env["accept_recording"]({**request(ids[0]), "userId": "different-account"}, sample)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("cross-account duplicate accepted")
    try:
        await env["accept_recording"]({**request(ids[0]), "meetingLink": request(ids[1])["meetingLink"]}, sample)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("cross-room duplicate accepted")
    sample.unlink()
    assert all(Path(job["file_path"]).is_file() for job in pending.values())
    assert all(verified_duration(Path(job["file_path"])) >= 2 for job in pending.values())

    # Exercise the actual delivery transaction around an external processing
    # failure: the four other files must complete while the failed file stays.
    async def processing(data, path):
        if data["botId"] == ids[0]:
            raise RuntimeError("simulated delivery timeout")
        if data["botId"] == ids[1] and data.get("_media_only"):
            return {"ok": True, "deferred": True}
        return {"ok": True}

    locked = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_process_recording_locked")
    env.update(active_delivery_jobs=0, _process_recording_inner=processing)
    exec(compile(ast.Module(body=[locked], type_ignores=[]), "main.py", "exec"), env)
    files = {eid: Path(pending[eid]["file_path"]) for eid in ids}
    def delivery(eid):
        job = pending[eid]
        return {"botId": eid, "userId": job["chat_id"], "meetingLink": job["meeting_link"], "filename": job["filename"], "_media_only": True}
    results = await asyncio.gather(*(env["_process_recording_locked"](delivery(eid), files[eid]) for eid in ids), return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert files[ids[0]].is_file() and pending[ids[0]]["last_error"]
    assert files[ids[1]].is_file() and pending[ids[1]]["media_complete"]
    assert all(not files[eid].exists() for eid in ids[2:])
    assert set(state["completed_deliveries"]) == set(ids[2:])
    assert env["active_delivery_jobs"] == 0
    assert (await env["_process_recording_locked"]({**delivery(ids[1]), "_media_only": False}, files[ids[1]]))["ok"]
    assert ids[1] in state["completed_deliveries"] and not files[ids[1]].exists()
    assert files[ids[0]].is_file()
    orphans = capture / 'same-account' / 'new-crash-job'
    orphans.mkdir(parents=True)
    orphan = orphans / 'capture.webm'
    shutil.copyfile(files[ids[0]], orphan)
    job = {'chat_id':'same-account','meet_url':'https://meet.google.com/abc-defg-hij','worker_url':'http://lane','status':'recording','premium':True}
    state['launched_events']['new-crash-job'] = job
    recovery = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'recover_exact_worker_source')
    env.update(RECORDING_ROOT=capture, re=re, PENDING_DELIVERY_MAX_ATTEMPTS=8)
    exec(compile(ast.Module(body=[recovery], type_ignores=[]), 'main.py', 'exec'), env)
    assert await env['recover_exact_worker_source']('new-crash-job', job) is True
    assert orphan.is_file() and Path(state['pending_deliveries']['new-crash-job']['file_path']).is_file()
    assert await env['recover_exact_worker_source']('unknown-job', job) is False
    assert await env['recover_exact_worker_source']('new-crash-job', {**job, 'worker_url':None}) is False
    print('EXACT_CRASHED_WORKER_SOURCE_RECOVERY_PASS')
    print("INDEPENDENT_DELIVERY_FAILURE_AND_DEFERRED_TRANSCRIPT_PASS")
    print("FIVE_SAME_ACCOUNT_DURABLE_AV_HANDOFF_PASS")


with tempfile.TemporaryDirectory() as path:
    asyncio.run(test(Path(path)))
