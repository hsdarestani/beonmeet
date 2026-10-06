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
]
for needle in required_main:
    assert needle in MAIN, f"missing auto calendar invariant: {needle}"

assert I18N.count('"auto_enabled"') == 3
assert I18N.count('"auto_disabled"') == 3
assert I18N.count('"auto_connect"') == 3
assert I18N.count('"auto":') >= 6
assert 'BUTTON_ACTIONS[_labels["auto"]] = "/auto"' in I18N

print("AUTO_CALENDAR_TEST_PASS")

assert 'if ADMINUSER and str(chat_id) == ADMINUSER and TOKEN_FILE.exists()' not in MAIN
