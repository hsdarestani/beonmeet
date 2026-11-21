#!/usr/bin/env python3
"""Fail-closed configurable capture quality overlay for pinned BeOnMeet worker.

Low = original 5-slot experimental profile, balanced = clearer promotional
baseline, high = requires dedicated, separately load-tested recording server.
Never modify an active worker or a source file in place.
"""
from pathlib import Path
import argparse

OLD = '''                for (const track of stream.getVideoTracks()) {
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
                });'''

NEW = '''                // The five-slot trial on a shared VPS uses a moderate profile.
                // High requires real 5-room capacity QA on a stronger server.
                const qualityName = String(process.env.BEONMEET_CAPTURE_QUALITY || 'balanced').toLowerCase();
                const recordingQuality = qualityName === 'high'
                    ? { width: 1280, height: 720, fps: 15, maxFps: 15, video: 1200000, audio: 96000 }
                    : qualityName === 'low'
                        ? { width: 640, height: 360, fps: 8, maxFps: 10, video: 320000, audio: 64000 }
                        : { width: 854, height: 480, fps: 10, maxFps: 12, video: 650000, audio: 96000 };
                for (const track of stream.getVideoTracks()) {
                    try {
                        await track.applyConstraints({
                            width: { ideal: recordingQuality.width },
                            height: { ideal: recordingQuality.height },
                            frameRate: { ideal: recordingQuality.fps, max: recordingQuality.maxFps },
                        });
                    } catch (e) {
                        console.warn('Capture constraints unavailable; retaining original stream', e);
                    }
                }
                const mediaRecorder = new MediaRecorder(stream, {
                    mimeType: selectedMimeType,
                    videoBitsPerSecond: recordingQuality.video,
                    audioBitsPerSecond: recordingQuality.audio,
                });'''


def patched_source(source: str) -> str:
    if source.count(OLD) != 1 or "const recordingQuality =" in source:
        raise ValueError("Unknown/already-upgraded worker; refuse unsafe patch")
    return source.replace(OLD, NEW, 1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    args = p.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refuse in-place modification")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("CAPTURE_QUALITY_PROFILE_OVERLAY_READY")
