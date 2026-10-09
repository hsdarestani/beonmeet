#!/usr/bin/env python3
"""Regression: revoked shared Google OAuth must never block healthy personal meetings."""
import ast
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
module = ast.parse(main_source)

def extract(name, namespace):
    node = next(n for n in module.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "app/main.py", "exec"), namespace)
    return namespace[name]

class Token:
    def exists(self): return True

class StopLoop(BaseException): pass

class AsyncMock:
    @staticmethod
    async def to_thread(fn, *args): return fn(*args)
    @staticmethod
    async def sleep(_): raise StopLoop()

now = datetime.now(timezone.utc)
event = {
    "id": "valid-personal-event",
    "_calendarId": "primary",
    "start": {"dateTime": (now - timedelta(minutes=2)).isoformat()},
    "end": {"dateTime": (now + timedelta(minutes=40)).isoformat()},
}
seen = []
async def save_state(): pass
async def maybe_launch_event(e, req, url, at):
    seen.append((e["id"], url, req["chat_id"]))
    return True

def events(chat_id=None):
    if chat_id is None:
        raise RuntimeError("invalid_grant: legacy token revoked")
    return [event]

def event_start(e):
    return datetime.fromisoformat(e["start"]["dateTime"])

def event_end(e):
    return datetime.fromisoformat(e["end"]["dateTime"])

state = {"requests": {}, "auto_join_all": {"42": True}, "auto_registered_events": {}, "launched_events": {}}
scan = {}
env = {
    "Any": Any, "asyncio": AsyncMock, "datetime": datetime, "timezone": timezone,
    "timedelta": timedelta, "uuid": uuid, "TOKEN_FILE": Token(),
    "state": state, "calendar_scan_status": scan, "list_calendar_events": events,
    "calendar_connected": lambda cid: True, "is_premium": lambda cid: True,
    "event_meet_url": lambda e: "https://meet.google.com/abc-defg-hij",
    "event_declined_by_owner": lambda e: False, "event_start": event_start,
    "event_end": event_end, "user_language": lambda cid: "en",
    "record_request": lambda *args: None, "save_state": save_state,
    "maybe_launch_calendar_event": maybe_launch_event, "CALENDAR_POLL_SECONDS": 30,
}
calendar_loop = extract("calendar_loop", env)
try:
    asyncio.run(calendar_loop())
except StopLoop:
    pass

assert seen == [("auto-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "beonmeet:42:primary:valid-personal-event")), "https://meet.google.com/abc-defg-hij", "42")], seen
assert scan["42"]["status"] == "ok", scan
assert scan["__legacy_error"]["reason"] == "RuntimeError"

# The same revoked shared token must not poison manual personal calendar lookup.
manual_env = {
    "Any": Any, "TOKEN_FILE": Token(),
    "google_token_file": lambda chat: Token(),
    "personal_calendar_scopes_ready": lambda chat: True,
    "list_calendar_events": events, "event_meet_url": env["event_meet_url"],
    "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
    "event_start": event_start, "event_end": event_end,
}
lookup = extract("find_calendar_event_for_meet", manual_env)
assert lookup("https://meet.google.com/abc-defg-hij", "42")["id"] == "valid-personal-event"
print("LEGACY_CALENDAR_REVOCATION_ISOLATION_PASS")
