#!/usr/bin/env python3
"""Executable regression tests for Calendar auto-join fixes, without production secrets."""
import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
module = ast.parse(source)
functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}


def extract(name, environment):
    node = functions[name]
    isolated = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), filename="app/main.py", mode="exec"), environment)
    return environment[name]


def normalize_meet_url(value):
    match = re.search(r"(?:https?://)?meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", value or "", re.I)
    return ("https://" + match.group(0).removeprefix("https://")).lower() if match else ""


get_meet = extract("event_meet_url", {"Any": Any, "normalize_meet_url": normalize_meet_url})
assert get_meet({
    "hangoutLink": "https://meet.google.com/invalid-link",
    "conferenceData": {"entryPoints": [{"uri": "https://meet.google.com/uje-pcht-tiw"}]},
}) == "https://meet.google.com/uje-pcht-tiw"
assert get_meet({"description": "Join: https://meet.google.com/uje-pcht-tiw"}) == "https://meet.google.com/uje-pcht-tiw"
assert get_meet({"conferenceData": None, "hangoutLink": None}) == ""

class Reply:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.payload


class FakeSettings:
    def get(self, **kwargs):
        return Reply({"value": "UTC"})


class FakeEvents:
    def __init__(self, fail=False):
        self.fail = fail

    def list(self, **kwargs):
        if self.fail:
            return Reply(error=RuntimeError("Google API unavailable"))
        return Reply({"items": [{"id": "event-123", "start": {"dateTime": "2026-10-08T14:00:00Z"}}]})


class FakeService:
    def __init__(self, fail=False):
        self.fail = fail

    def settings(self):
        return FakeSettings()

    def events(self):
        return FakeEvents(self.fail)


def run_calendar(fail=False):
    svc = FakeService(fail)
    namespace = {
        "Any": Any,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "load_google_credentials": lambda chat_id: object(),
        "build": lambda *args, **kwargs: svc,
        "_calendar_entries": lambda *args, **kwargs: [{"id": "primary"}],
    }
    func = extract("list_calendar_events", namespace)
    return func(chat_id="42")

assert run_calendar()[0]["id"] == "event-123"
try:
    run_calendar(fail=True)
except RuntimeError as exc:
    assert "all calendars" in str(exc)
else:
    raise AssertionError("All failed calendars must not look like an empty schedule")

status = extract("auto_calendar_status_message", {
    "Any": Any,
    "calendar_connected": lambda chat_id: True,
    "auto_join_enabled": lambda chat_id: True,
    "calendar_scan_status": {"42": {"status": "ok", "checked_at": "2026-10-08T11:00:00+00:00", "events": 3, "meetings": 2}},
    "calendar_auth_url": lambda chat_id: "https://example.test/auth/google?chat_id=42",
})
text = status("42")
assert "ON" in text and "Meet events found: 2" in text
assert "reconnect required" not in text

requirements = (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")
assert "faster-whisper==1.2.1" in requirements
assert "av==18.1.0" in requirements
print("AUTO_CALENDAR_BEHAVIOR_TEST_PASS")
