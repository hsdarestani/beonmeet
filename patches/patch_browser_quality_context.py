#!/usr/bin/env python3
"""Pass capture quality into Playwright browser evaluation rather than reading Node process.env inside Meet.

Fail-closed, minimal compiled overlay. Google's browser context does not provide
Node's process global; a ReferenceError aborts recordMeetingPage immediately
after "Media Recorder will use...", closes Meet in join finally and never
sends recording-started to the controller.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MARKER = "BEONMEET_BROWSER_QUALITY_ARG_V1"
SIG_OLD = "await this.page.evaluate(async ({ teamId, duration, inactivityLimit, loneParticipantExitDelayMs, userId, slightlySecretId, activateInactivityDetectionAfter, activateInactivityDetectionAfterMinutes, mimeTypes }) => {"
SIG_NEW = "await this.page.evaluate(async ({ teamId, duration, inactivityLimit, loneParticipantExitDelayMs, userId, slightlySecretId, activateInactivityDetectionAfter, activateInactivityDetectionAfterMinutes, mimeTypes, captureQuality }) => {"
QUALITY_OLD = "const qualityName = String(process.env.BEONMEET_CAPTURE_QUALITY || 'balanced').toLowerCase();"
QUALITY_NEW = "// " + MARKER + ": Browser receives value from Node. No process.env inside page.evaluate.\n                const qualityName = String(captureQuality || 'balanced').toLowerCase();"
ARGS_OLD = "            mimeTypes\n        });"
ARGS_NEW = "            mimeTypes,\n            captureQuality: process.env.BEONMEET_CAPTURE_QUALITY || 'balanced'\n        });"


def patched_source(source: str) -> str:
    if MARKER in source:
        raise ValueError("Already patched")
    for old in (SIG_OLD, QUALITY_OLD, ARGS_OLD):
        if source.count(old) != 1:
            raise ValueError(f"Unsupported compiled worker source (anchor count {source.count(old)})")
    output = source.replace(SIG_OLD, SIG_NEW, 1)
    output = output.replace(QUALITY_OLD, QUALITY_NEW, 1)
    output = output.replace(ARGS_OLD, ARGS_NEW, 1)
    assert output.count(MARKER) == 1
    assert output.count("String(process.env.BEONMEET_CAPTURE_QUALITY") == 0
    assert output.count("captureQuality: process.env.BEONMEET_CAPTURE_QUALITY") == 1
    assert output.count("const recordingQuality =") == 1
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refusing in-place modification")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("BROWSER_QUALITY_CONTEXT_FIX_STAGED")
