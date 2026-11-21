#!/usr/bin/env python3
"""Real SQLite wallet regression: welcome minutes accrue once, combine with purchases, and cannot create free-trial debt."""
from __future__ import annotations

import ast
import importlib.util
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(obj)
    return obj

wallet = module("credit_wallet", ROOT / "app/credit_wallet.py")
policy = module("billing_policy", ROOT / "app/billing_policy.py")
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE users (
 telegram_id TEXT PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
 last_name TEXT DEFAULT '', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 total_requests INT DEFAULT 0, total_recordings INT DEFAULT 0,
 premium_until TEXT, premium_plan TEXT);
CREATE TABLE subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT NOT NULL, plan_code TEXT,
 starts_at TEXT, ends_at TEXT, status TEXT, note TEXT);
CREATE TABLE recordings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, meet_url TEXT,
 filename TEXT, size_bytes INT, duration_seconds INT, created_at TEXT);
""")
wallet.create_wallet_schema(db)

source = (ROOT / "app/admin_panel.py").read_text(encoding="utf-8")
funcs = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
now = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
env = {
    "_db": lambda: db, "utcnow": lambda: now, "datetime": datetime,
    "timezone": timezone, "secrets": secrets,
    "wallet_balance": wallet.balance, "add_entry": wallet.add_entry,
    "has_wallet_history": wallet.has_wallet_history,
    "FREE_TRIAL_MINUTES": 60,
    "_active_legacy_subscription": lambda _who: None,
    "PUBLIC_PLAN_CODES": policy.PUBLIC_PLAN_CODES,
    "plan_quota_seconds": policy.plan_quota_seconds,
    "PAID_SALES_MAX_ACTIVE_USERS": 12,
    "PAID_SALES_MAX_SOLD_HOURS": 60,
    "is_premium": lambda who: False,
}
def extract(name: str):
    node = funcs[name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "app/admin_panel.py", "exec"), env)

for name in ("touch_user", "recording_credit_info", "record_recording",
             "credit_purchase", "is_premium", "free_recording_entitlement",
             "paid_sales_capacity"):
    extract(name)

def balance(who):
    return env["recording_credit_info"](who)

# First /start (touch_user) awards exactly one hour inside the same wallet.
env["touch_user"]("brandnew", "new")
assert balance("brandnew")["remaining_seconds"] == 3600
assert balance("brandnew")["trial_remaining_seconds"] == 3600
assert balance("brandnew")["paid_remaining_seconds"] == 0
assert not env["is_premium"]("brandnew"), "Free gift must not unlock premium worker pool"
assert env["free_recording_entitlement"]("brandnew")["allowed"]
assert env["paid_sales_capacity"]("basic")["active_users"] == 0, "Free trials do not count as paid active users"

env["touch_user"]("brandnew", "changed")
assert balance("brandnew")["remaining_seconds"] == 3600, "Repeated /start must not regrant"
assert db.execute("SELECT COUNT(*) FROM credit_entries WHERE telegram_id='brandnew' AND kind='trial'").fetchone()[0] == 1

env["record_recording"]("brandnew", "https://meet.google.com/abc-defg-hij", "test-1.webm", 1000, 900)
assert balance("brandnew")["remaining_seconds"] == 2700
env["record_recording"]("brandnew", "https://meet.google.com/abc-defg-hij", "test-1.webm", 1000, 900)
assert balance("brandnew")["remaining_seconds"] == 2700, "Retry must not debit twice"

# A free-only session longer than remaining gift consumes it, but must not
# leave debt that secretly subtracts from a later real customer payment.
env["record_recording"]("brandnew", "https://meet.google.com/abc-defg-hij", "overrun.webm", 1000, 4800)
assert balance("brandnew")["signed_balance_seconds"] == 0
assert balance("brandnew")["trial_remaining_seconds"] == 0
env["touch_user"]("brandnew")
assert balance("brandnew")["remaining_seconds"] == 0, "Used gift never returns"
assert env["credit_purchase"]("brandnew", "basic", "paid-1")["remaining_seconds"] == 7200
assert balance("brandnew")["paid_remaining_seconds"] == 7200
assert env["is_premium"]("brandnew"), "Bought credit unlocks paid priority"
assert env["paid_sales_capacity"]("basic")["active_users"] == 1

# After buying, earlier free minutes are consumed first. Paid entitlement remains
# usable even when a user's total debit exceeds their paid grant alone.
env["touch_user"]("buyer")
assert env["credit_purchase"]("buyer", "basic", "paid-2")["remaining_seconds"] == 10800
assert balance("buyer")["trial_remaining_seconds"] == 3600
assert balance("buyer")["paid_remaining_seconds"] == 7200
env["record_recording"]("buyer", "https://meet.google.com/abc-defg-hij", "paid-1.webm", 1000, 4500)
assert balance("buyer")["remaining_seconds"] == 6300
assert balance("buyer")["trial_remaining_seconds"] == 0
assert balance("buyer")["paid_remaining_seconds"] == 6300
assert env["is_premium"]("buyer")
assert env["paid_sales_capacity"]("basic")["sold_hours"] == round((7200 + 6300) / 3600, 2)

# Historic users with any completed recordings or past subscription must not
# receive a second trial on their next Telegram interaction.
now_s = now.isoformat()
db.execute("INSERT INTO users(telegram_id,first_seen,last_seen,total_recordings) VALUES(?,?,?,?)",
           ("pastfree", now_s, now_s, 1))
env["touch_user"]("pastfree")
assert balance("pastfree")["remaining_seconds"] == 0
db.execute("INSERT INTO users(telegram_id,first_seen,last_seen) VALUES(?,?,?)",
           ("oldsubscriber", now_s, now_s))
db.execute("INSERT INTO subscriptions(telegram_id,plan_code,starts_at,ends_at,status,note) VALUES(?,?,?,?,?,?)",
           ("oldsubscriber", "monthly", now_s, now_s, "active", "prior"))
env["touch_user"]("oldsubscriber")
assert balance("oldsubscriber")["remaining_seconds"] == 0

# Exact brand-new wallet showing 1h, no separate free recording-count machinery.
assert env["free_recording_entitlement"]("buyer")["remaining"] == 0
print("WELCOME_CREDIT_BEHAVIOR_TEST_PASS")


# A free hour can be consumed as four separate successful 15-minute sessions.
# Failed attempts and retries must not consume minutes.
env["touch_user"]("four-short-meetings")
assert balance("four-short-meetings")["trial_remaining_seconds"] == 3600
for index in range(4):
    env["record_recording"]("four-short-meetings",
                            "https://meet.google.com/abc-defg-hij",
                            f"quarter-{index}.webm", 125_000, 900)
    expected = 3600 - (index + 1) * 900
    assert balance("four-short-meetings")["trial_remaining_seconds"] == expected
    assert balance("four-short-meetings")["remaining_seconds"] == expected
    env["record_recording"]("four-short-meetings",
                            "https://meet.google.com/abc-defg-hij",
                            f"quarter-{index}.webm", 125_000, 900)
    assert balance("four-short-meetings")["remaining_seconds"] == expected, "Duplicate delivery cannot debit again"
assert db.execute(
    "SELECT COUNT(*) FROM credit_entries WHERE telegram_id=? AND kind='recording'",
    ("four-short-meetings",)
).fetchone()[0] == 4
assert db.execute(
    "SELECT COALESCE(SUM(duration_seconds),0) FROM recordings WHERE telegram_id=?",
    ("four-short-meetings",)
).fetchone()[0] == 3600

env["touch_user"]("failed-prejoin")
before = balance("failed-prejoin")["remaining_seconds"]
# Telegram join requests are recorded separately: they never touch the wallet.
assert before == 3600
assert db.execute(
    "SELECT COUNT(*) FROM credit_entries WHERE telegram_id=? AND kind='recording'",
    ("failed-prejoin",)
).fetchone()[0] == 0
assert balance("failed-prejoin")["remaining_seconds"] == before
print("FREE_HOUR_FOUR_FIFTEEN_MINUTE_SESSIONS_TEST_PASS")
