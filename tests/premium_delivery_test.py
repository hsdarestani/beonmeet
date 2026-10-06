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
