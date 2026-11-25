#!/usr/bin/env python3
"""Fail-closed checks for bounded finalization of the pinned deployed worker."""
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("finalization_patch", root / "patches/patch_recording_finalization.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

anchors = (mod.BRIDGE, mod.DATA, mod.CALLBACK_START, mod.CALLBACK_END, mod.START, mod.CHAIN, mod.WRITE, mod.CHUNK_ERROR,
           mod.STOP_HANDLER, mod.STOP_CLEAN, mod.STOP_OPEN, mod.STOP_CLOSE, mod.END, mod.END_LISTENERS, mod.COUNT_FAILURE, mod.COUNT_READ,
           mod.ALONE, mod.EVALUATE, mod.TAIL)
sample = "\n\n".join(anchors)
changed = mod.patched_source(sample)
assert changed.count(mod.MARKER) == 1
assert changed.index("const waitingPromise =") < changed.index("screenAppSendData")
assert changed.count("const waitingPromise =") == 1
assert "recordingPage.once('close', pageTerminated)" in changed
assert "recordingPage.once('crash', pageTerminated)" in changed
assert "recordingPage.off('close', pageTerminated)" in changed
assert "MediaRecorder stop deadline exceeded" in changed
assert "Recording flush deadline exceeded" in changed
assert "Recording chunk deadline exceeded" in changed
assert "Capture initialization deadline exceeded" in changed
assert "track.addEventListener('ended', finalizeEndedCapture" in changed
assert "recording_limit_seconds" in changed
assert "walletHardTimer = setTimeout(finalizeEndedCapture, 30000)" in changed
assert "context.browser()?.close()" not in changed
assert "document.body.innerText?.toString()" not in changed
assert "loneTestDetectionActive = false" not in changed
assert "contributors === 1" in changed
assert "aloneSince = null" in changed
for bad in (changed, sample.replace(mod.BRIDGE, "missing the required anchor")):
    try:
        mod.patched_source(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("Unexpected upstream layout must not be deployed")
print("BOUNDED_RECORDING_FINALIZATION_OVERLAY_TEST_PASS")
