#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

required_admin = [
    "google_calendar_email TEXT DEFAULT ''",
    "calendar_connected INTEGER NOT NULL DEFAULT 0",
    "all_meetings_enabled INTEGER NOT NULL DEFAULT 0",
    "calendar_connected_at TEXT",
    "def set_calendar_connection(",
    "def set_auto_join_enabled(",
    '("calendar", "/admin/calendar", "همه جلسات", "◎")',
    '@router.get("/admin/calendar", response_class=HTMLResponse)',
    "Google account",
    "All meetings",
    'href="/admin/calendar"',
]
for needle in required_admin:
    assert needle in ADMIN, f"missing admin calendar visibility invariant: {needle}"

required_main = [
    "def connected_google_calendar_email(",
    'if calendar.get("primary"):',
    "async def sync_calendar_admin_metadata()",
    "asyncio.create_task(sync_calendar_admin_metadata())",
    "set_calendar_connection,",
    "set_auto_join_enabled,",
    "await asyncio.to_thread(set_auto_join_enabled, str(chat_id), False)",
    "await asyncio.to_thread(set_auto_join_enabled, str(chat_id), enabled)",
    "google_email = await asyncio.to_thread(",
    "all_meetings_enabled=True",
]
for needle in required_main:
    assert needle in MAIN, f"missing Calendar metadata sync invariant: {needle}"

print("ADMIN_CALENDAR_VISIBILITY_TEST_PASS")
