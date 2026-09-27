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
]

for needle in required:
    assert needle in MAIN, f"missing premium delivery invariant: {needle}"

audio_flag = MAIN.index('pending_state["audio_delivered"] = True')
transcript_call = MAIN.index('transcribe_audio_local,', audio_flag)
assert audio_flag < transcript_call, "audio completion state must be persisted before transcription"

assert 'if not (audio_already_delivered and transcript_already_delivered):' in MAIN
assert 'if audio_delivery_error is not None or transcript_processing_error is not None:' in MAIN

print("PREMIUM_DELIVERY_TEST_PASS")

assert "manual-99a88a85-53f5-467b-908c-25b5c98aa78f" not in MAIN, "remove session-specific recovery hacks"
print("DELIVERY_IDEMPOTENCY_TEST_PASS")
