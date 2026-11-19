#!/usr/bin/env python3
"""Build a low-resource overlay for the pinned native Google Meet recorder.

This script ONLY transforms a copy of the compiled GoogleMeetBot.js. Never patch
a live container or replace the original image in place. The deployment script
must inspect and smoke-test the resulting overlay before enabling five slots.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD_CODEC = "const selectedMimeType = mimeTypes.find((mimeType) => MediaRecorder.isTypeSupported(mimeType));"
NEW_CODEC = "const selectedMimeType = ['video/webm;codecs=vp8,opus', ...mimeTypes].find((mimeType) => MediaRecorder.isTypeSupported(mimeType));"
OLD_RECORDER = "const mediaRecorder = new MediaRecorder(stream, { mimeType: selectedMimeType });"
NEW_RECORDER = """// Shared 3-vCPU VPS: favor low-bitrate VP8 instead of five software VP9 encoders.
                for (const track of stream.getVideoTracks()) {
                    try {
                        await track.applyConstraints({
                            width: { ideal: 640 },
                            height: { ideal: 360 },
                            frameRate: { ideal: 8, max: 10 },
                        });
                    } catch (e) {
                        console.warn('Low-resource capture constraints unavailable; retaining original stream', e);
                    }
                }
                const mediaRecorder = new MediaRecorder(stream, {
                    mimeType: selectedMimeType,
                    videoBitsPerSecond: 320000,
                    audioBitsPerSecond: 64000,
                });"""


def patched_source(source: str) -> str:
    """Fail closed when compiled upstream changes or a patch already exists."""
    if source.count(OLD_CODEC) != 1:
        raise ValueError("Expected exactly one unpatched codec selection")
    if source.count(OLD_RECORDER) != 1:
        raise ValueError("Expected exactly one unpatched MediaRecorder construction")
    result = source.replace(OLD_CODEC, NEW_CODEC).replace(OLD_RECORDER, NEW_RECORDER)
    assert result.count(NEW_CODEC) == 1 and result.count(NEW_RECORDER) == 1
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Unmodified compiled GoogleMeetBot.js")
    parser.add_argument("destination", type=Path, help="Versioned overlay file for container bind-mount")
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refuse to modify original source in place")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("LOW_RESOURCE_RECORDER_OVERLAY_PATCHED")
