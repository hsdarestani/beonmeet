#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "patches" / "apply-upstream-fixes.py").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

required_patch_markers = [
    "SILENCE_AUTOSTOP_PATCH_MARKER_NOT_FOUND",
    "INITIAL_ALONE_PATCH_MARKER_NOT_FOUND",
    "INITIAL_ALONE_GRACE_PATCH_MARKER_NOT_FOUND",
    "MEET_PAGE_DEBOUNCE_PATCH_MARKER_NOT_FOUND",
    "audio silence is not a meeting-end signal",
    "return false;",
    "maxInvalidMeetUiChecks = 6",
    "Google Meet page stayed invalid for 60s",
]

for needle in required_patch_markers:
    assert needle in PATCH, f"missing recorder end guard invariant: {needle}"

assert COMPOSE.count('LONE_PARTICIPANT_EXIT_DELAY_SECONDS: "120"') == 3
print("RECORDER_END_GUARD_TEST_PASS")
