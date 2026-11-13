#!/usr/bin/env python3
"""Execute quota + payment-idempotency functions against a real SQLite database."""
from __future__ import annotations
import ast
import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("billing_policy", ROOT / "app/billing_policy.py")
policy = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(policy)
source = (ROOT / "app/admin_panel.py").read_text(encoding="utf-8")
module = ast.parse(source)
functions = {
    node.name: node for node in module.body if isinstance(node, ast.FunctionDef)
}
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE users (
 telegram_id TEXT PRIMARY KEY, premium_until TEXT, premium_plan TEXT,
 total_recordings INTEGER DEFAULT 0, last_seen TEXT
);
CREATE TABLE subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, plan_code TEXT,
 price_toman INTEGER, starts_at TEXT, ends_at TEXT, status TEXT,
 note TEXT, created_at TEXT
);
CREATE TABLE recordings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, meet_url TEXT,
 filename TEXT, size_bytes INTEGER, duration_seconds INTEGER, created_at TEXT
);
""")
NOW = datetime(2026, 11, 13, 11, 0, tzinfo=timezone.utc)
env = {
    "_db": lambda: db,
    "utcnow": lambda: NOW,
    "datetime": datetime,
    "timedelta": timedelta,
    "timezone": timezone,
    "PLANS": policy.PLANS,
    "plan_quota_seconds": policy.plan_quota_seconds,
    "remaining_seconds": policy.remaining_seconds,
}
for name in ("_parse_dt", "subscription_info", "paid_recording_entitlement",
             "record_recording", "activate_subscription"):
    node = functions[name]
    isolated = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), filename="app/admin_panel.py", mode="exec"), env)

def insert_user(user_id: str, plan: str):
    db.execute(
        "INSERT INTO users(telegram_id,premium_until,premium_plan,total_recordings) VALUES(?,?,?,0)",
        (user_id, "2026-12-01T11:00:00+00:00", plan),
    )
    db.execute(
        "INSERT INTO subscriptions(telegram_id,plan_code,price_toman,starts_at,ends_at,status,note,created_at) VALUES(?,?,?,?,?,'active','initial',?)",
        (user_id, plan, policy.PLANS[plan]["price"], "2026-11-01T11:00:00+00:00",
         "2026-12-01T11:00:00+00:00", NOW.isoformat()),
    )
    db.commit()

insert_user("42", "basic")
env["record_recording"]("42", "https://meet.google.com/abc-defg-hij", "first.webm", 1500, 3600)
assert env["paid_recording_entitlement"]("42")["remaining_seconds"] == 3600
env["record_recording"]("42", "https://meet.google.com/abc-defg-hij", "second.webm", 2500, 1800)
env["record_recording"]("42", "https://meet.google.com/abc-defg-hij", "second.webm", 2500, 1800)
assert db.execute("SELECT COUNT(*) FROM recordings WHERE telegram_id='42'").fetchone()[0] == 2
assert env["paid_recording_entitlement"]("42")["remaining_seconds"] == 1800
env["record_recording"]("42", "https://meet.google.com/abc-defg-hij", "third.webm", 5000, 1900)
assert env["paid_recording_entitlement"]("42")["allowed"] is False
assert env["paid_recording_entitlement"]("42")["remaining_seconds"] == 0

insert_user("legacy", "monthly")
assert env["paid_recording_entitlement"]("legacy")["remaining_seconds"] is None
assert env["paid_recording_entitlement"]("legacy")["allowed"] is True

# A purchase during the current period is scheduled for the next period.
renewal = env["activate_subscription"]("42", "pro", "Zibal receipt 9898")
assert renewal == datetime(2026, 12, 31, 11, 0, tzinfo=timezone.utc)
assert env["subscription_info"]("42")["plan"] == "basic", "future renewal must not overwrite current entitlement"
same = env["activate_subscription"]("42", "pro", "Zibal receipt 9898")
assert same == renewal
assert db.execute(
    "SELECT COUNT(*) FROM subscriptions WHERE telegram_id='42' AND note='Zibal receipt 9898'"
).fetchone()[0] == 1
print("BILLING_USAGE_BEHAVIOR_TEST_PASS")
