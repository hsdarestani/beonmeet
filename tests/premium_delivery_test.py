#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

required = [
    'WHISPER_MODEL", "large-v3"',
    'TRANSCRIPTION_CHUNK_SECONDS", "120"',
    'language=None',
    '"64k"',
    'async def send_audio_to_recipients',
    'pending_state["audio_delivered"] = True',
    'pending_state["transcript_delivered"] = True',
    'premium downstream delivery incomplete',
    'large_audio_download',
    'delivery_locks: dict[str, asyncio.Lock] = {}',
    'async with lock:',
    '"duplicate": True',
    '"source_name": raw_path.name',
    'missing exact event/chat/file identity',
    'event mismatch',
    'primary transcription failed; trying recovery model:',
    'transcribe_audio_recovery_fast,',
    'video_delivered_after_failure',
    'recording delivered; downstream Premium output remains pending:',
]

for needle in required:
    assert needle in MAIN, f"missing premium delivery invariant: {needle}"

audio_flag = MAIN.index('pending_state["audio_delivered"] = True')
transcript_call = MAIN.index('transcribe_audio_local,', audio_flag)
assert audio_flag < transcript_call, "audio completion state must be persisted before transcription"

assert 'if not (audio_already_delivered and transcript_already_delivered):' in MAIN
assert 'if audio_delivery_error is not None or transcript_processing_error is not None:' in MAIN
local_call = MAIN.index('transcribe_audio_local,')
assert MAIN.find('transcribe_audio_recovery_fast,', local_call) > local_call
assert 'if not bool(data.get("_silent_retry")) and not video_delivered_after_failure:' in MAIN

print("PREMIUM_DELIVERY_TEST_PASS")

assert "manual-99a88a85-53f5-467b-908c-25b5c98aa78f" not in MAIN, "remove session-specific recovery hacks"
print("DELIVERY_IDEMPOTENCY_TEST_PASS")

assert "_legacy_orphan_candidates" not in MAIN
assert "_recover_legacy_orphan" not in MAIN
assert 'RECORDING_ROOT.glob("*/*")' not in MAIN
print("NO_STALE_RECORDING_RECOVERY_TEST_PASS")

assert 'PREMIUM_DOWNLOAD_TTL_HOURS = max(1, int(os.environ.get("PREMIUM_DOWNLOAD_TTL_HOURS", "72")))' in MAIN
assert 'FREE_DOWNLOAD_TTL_HOURS = max(' in MAIN
assert 'async def recording_download_ttl_hours' in MAIN
assert 'return PREMIUM_DOWNLOAD_TTL_HOURS' in MAIN
assert 'return FREE_DOWNLOAD_TTL_HOURS' in MAIN
assert '"ttl_hours": ttl_hours' in MAIN
assert 'return f"https://{DOMAIN}/download/{token}", ttl_hours' in MAIN
assert 'download_url, expires_hours = await create_recording_download(' in MAIN
assert 'hours=expires_hours' in MAIN
assert 'download_url, download_hours = await create_recording_download(' in MAIN
assert 'hours=download_hours' in MAIN
print("PREMIUM_RETENTION_72H_TEST_PASS")


# A missing file on the controller must never be acknowledged to the recorder
# unless a verified, persisted delivery receipt matches the exact event/chat/path.
# Without this guard, the recorder deletes its only WebM copy on a false 200.
import ast
import asyncio
from typing import Any

class HttpError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code

async def completed_stub(*args, **kwargs):
    return {"ok": True, "processed": True}

module = ast.parse(MAIN)
fn_node = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_process_recording")
env = {
    "Any": Any, "Path": Path, "asyncio": asyncio,
    "state": {"pending_deliveries": {}, "completed_deliveries": {}},
    "delivery_locks": {},
    "HTTPException": HttpError,
    "_process_recording_locked": completed_stub,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn_node], type_ignores=[])), "app/main.py", "exec"), env)
process = env["_process_recording"]
source = Path("/unmounted-recorder-path/recording-test-missing.webm")
data = {"userId": "123", "eventId": "evt-1", "filename": source.name}

for case in ("no_receipt", "different_chat", "different_filename", "different_source"):
    env["state"]["completed_deliveries"] = {}
    if case != "no_receipt":
        env["state"]["completed_deliveries"]["evt-1"] = {
            "chat_id": "456" if case == "different_chat" else "123",
            "filename": "other.webm" if case == "different_filename" else source.name,
            "source_path": "/other/source.webm" if case == "different_source" else str(source),
            "completed_at": "2026-11-21T10:00:00+00:00",
        }
    try:
        asyncio.run(process(data, source))
    except HttpError as error:
        assert error.status_code == 404, (case, error)
    else:
        raise AssertionError(f"Unverified missing recording must fail closed: {case}")

env["state"]["completed_deliveries"]["evt-1"] = {
    "chat_id": "123", "filename": source.name, "source_path": str(source),
    "completed_at": "2026-11-21T10:00:00+00:00",
}
assert asyncio.run(process(data, source))["duplicate"] is True

assert "state.setdefault(\"completed_deliveries\", {})[pending_id]" in MAIN
assert '"completed_deliveries": {}' in MAIN
assert 'state.setdefault("completed_deliveries", {})' in MAIN
print("MISSING_RECORDING_MUST_NOT_ACK_SUCCESS_TEST_PASS")


# A preserved premium video that has exhausted eight retries must be eligible
# again after the recorder directory permission is repaired. The delivered
# video flag stays intact so only audio/transcript are regenerated.
assert 'PENDING_DELIVERY_MAX_ATTEMPTS = max(8, min(32,' in MAIN
assert 'if attempts >= PENDING_DELIVERY_MAX_ATTEMPTS:' in MAIN
assert '"recovery_exhausted_notified"' in MAIN
assert "if not video_already_delivered:" in MAIN
assert 'pending_state["video_delivered"] = True' in MAIN
assert (ROOT / "app" / "i18n.py").read_text(encoding="utf-8").count('"delivery_recovery_exhausted"') == 3
print("PREMIUM_PENDING_RETRY_AFTER_INFRA_REPAIR_TEST_PASS")
