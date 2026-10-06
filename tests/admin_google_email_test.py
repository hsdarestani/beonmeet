#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")

assert "https://www.googleapis.com/calendar/v3/users/me/calendarList" in ADMIN
assert "https://www.googleapis.com/calendar/v3/calendars/primary" not in ADMIN
assert '"primary"' in ADMIN
assert "calendar.calendarlist.readonly" in ADMIN
assert "HTTP {status}" in ADMIN

print("ADMIN_GOOGLE_EMAIL_TEST_PASS")
