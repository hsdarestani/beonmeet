#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
I18N = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")

required_main = [
    'USER_TOKEN_DIR = DATA_DIR / "google-tokens"',
    '"https://www.googleapis.com/auth/calendar.calendarlist.readonly"',
    'def personal_calendar_scopes_ready',
    'Never fall back to the legacy shared bot token',
    'return google_token_file(chat_id)',
    'def _calendar_entries',
    'service.calendarList().list(',
    'all_calendars = chat_id is not None',
    'def google_token_file',
    'def calendar_connected',
    'def auto_join_enabled',
    'def calendar_auth_url',
    'def event_declined_by_owner',
    'def same_meeting_inflight',
    'async def maybe_launch_calendar_event',
    'state.setdefault("auto_join_all", {})',
    '"auto_calendar"',
    'uuid.uuid5(',
    'event["google_calendar_id"] = calendar_id',
    'event["id"] = f"auto-{stable_event_key}"',
    'if source_event.get("status") == "cancelled" or event_declined_by_owner(source_event):',
    'google_token_file(chat_id).write_text(creds.to_json())',
    'globals()["state"].setdefault("auto_join_all", {})[chat_id] = True',
    'if not await asyncio.to_thread(is_premium, str(chat_id)):',
    'Premium required for All meetings',
    'await send_subscription_offer(chat_id, "auto_premium_only")',
]
for needle in required_main:
    assert needle in MAIN, f"missing auto calendar invariant: {needle}"

assert I18N.count('"auto_enabled"') == 3
assert I18N.count('"auto_disabled"') == 3
assert I18N.count('"auto_connect"') == 3
assert I18N.count('"auto_premium_only"') == 3
assert I18N.count('"auto_premium_status"') == 3
assert I18N.count('"auto":') == 3, "old keyboard labels are retained only to handle stale Telegram keyboards"
assert 'BUTTON_ACTIONS[_labels["auto"]] = "/auto"' in I18N

print("AUTO_CALENDAR_TEST_PASS")

assert 'if ADMINUSER and str(chat_id) == ADMINUSER and TOKEN_FILE.exists()' not in MAIN

# Automatic mode must never turn itself off when /auto is tapped repeatedly.
assert 'enabled = not auto_join_enabled(chat_id)' not in MAIN
assert 'def auto_calendar_status_message' in MAIN
assert '"status": "reconnect"' in MAIN
assert 'if calendar_count and calendar_failures == calendar_count:' in MAIN
assert 'calendar_scan_status[chat_id]' in MAIN
assert 'Google Calendar event listing failed for all calendars' in MAIN
assert 'av==18.1.0' in (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")
print("AUTO_CALENDAR_AND_TRANSCRIPTION_DEPENDENCY_FIX_PASS")


# Verify that a worker transport failure does not silently discard an
# immediate or calendar join. Both a busy worker and an unreachable worker
# must enter the existing durable queue; 202 means only accepted, not admitted.
import ast
import asyncio
from typing import Any

module = ast.parse(MAIN)
launch_node = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "launch_meeting")

async def _allowed(*args, **kwargs):
    return True

async def _ignore_text(*args, **kwargs):
    return None

for accepted, busy in ((False, False), (False, True), (True, False)):
    queued, notifications = [], []

    async def dispatch(*args, **kwargs):
        return accepted, busy, "free-1" if accepted else ""

    async def enqueue(*args, **kwargs):
        queued.append((args, kwargs))

    async def send_text(chat_id, message, **kwargs):
        notifications.append(message)

    env = {
        "Any": Any,
        "asyncio": asyncio,
        "is_premium": lambda chat_id: False,
        "_queue_event_id": lambda event: event["id"],
        "_free_recording_allowed": _allowed,
        "_paid_recording_allowed": _allowed,
        "_dispatch_meeting": dispatch,
        "enqueue_meeting": enqueue,
        "tg_text": send_text,
        "t": lambda chat_id, key, **kwargs: key,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[launch_node], type_ignores=[])), "app/main.py", "exec"), env)
    outcome = asyncio.run(env["launch_meeting"](
        {"id": "manual-regression-test"}, {"chat_id": "1234"}, "https://meet.google.com/abc-defg-hij"
    ))
    assert outcome is accepted
    assert len(queued) == (0 if accepted else 1), (accepted, busy, queued)
    if not accepted:
        assert queued[0][0][-1] is False
        assert queued[0][1]["notify"] is True
        assert not notifications, "queue notification is owned by enqueue_meeting"
    else:
        assert notifications == ["launch_free"], notifications

print("DISPATCH_FAILURE_DURABLE_RETRY_TEST_PASS")


# Manual /now must not launch duplicate Chrome tabs for repeated Meet links.
# It must also allow retries after a genuinely stale failed launch.
import ast
from datetime import datetime, timedelta, timezone
from dateutil.parser import isoparse

module = ast.parse(MAIN)
helpers = {
    node.name: node for node in module.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
node = helpers["recent_manual_join_inflight"]
env = {"datetime": datetime, "timedelta": timedelta, "timezone": timezone, "isoparse": isoparse, "state": {}}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
             "app/main.py", "exec"), env)
recent_manual = env["recent_manual_join_inflight"]
now = datetime(2026, 11, 21, 10, 50, tzinfo=timezone.utc)
meet = "https://meet.google.com/abc-defg-hij"
other = "https://meet.google.com/def-ghij-klm"

def seed(status, minutes, meet_url=meet, chat_id="testuser"):
    env["state"]["launched_events"] = {
        "evt": {"status": status, "meet_url": meet_url, "chat_id": chat_id,
                "launched_at": (now - timedelta(minutes=minutes)).isoformat()}
    }
    env["state"]["join_queue"] = []

for status in ("joining", "waiting_for_admission", "remote_claimed", "recording"):
    seed(status, 2)
    assert recent_manual("testuser",meet,now),status
    seed(status, 9)
    assert not recent_manual("testuser",meet,now),status
seed("joining", 2, other)
assert not recent_manual("testuser",meet,now)
seed("joining", 2, meet, "somebody-else")
assert not recent_manual("testuser",meet,now)
env["state"]["launched_events"] = {}
env["state"]["join_queue"] = [{
    "event_id": "queued", "req": {"chat_id": "testuser"}, "meet_url": meet
}]
assert recent_manual("testuser",meet,now)
assert not recent_manual("another-user",meet,now)

assert 'if force_now and recent_manual_join_inflight(' in MAIN
assert '"joining": timedelta(minutes=20)' in MAIN
assert '"recording": timedelta(hours=6)' in MAIN
assert I18N.count('"join_already_processing"') == 3
print("MANUAL_JOIN_DEDUP_AND_STALE_CLEANUP_TEST_PASS")
