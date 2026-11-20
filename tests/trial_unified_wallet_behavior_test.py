#!/usr/bin/env python3
"""Real SQLite behavioral QA for once-only introductory credit in the shared wallet."""
from __future__ import annotations

import ast
import importlib.util
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


policy = load_module("billing_policy", ROOT / "app/billing_policy.py")
wallet = load_module("credit_wallet", ROOT / "app/credit_wallet.py")
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE users (
 telegram_id TEXT PRIMARY KEY, username TEXT DEFAULT '',
 first_name TEXT DEFAULT '', last_name TEXT DEFAULT '',
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 total_requests INTEGER NOT NULL DEFAULT 0,
 total_recordings INTEGER NOT NULL DEFAULT 0,
 premium_until TEXT, premium_plan TEXT
);
CREATE TABLE subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, plan_code TEXT,
 price_toman INTEGER, starts_at TEXT, ends_at TEXT,
 status TEXT DEFAULT 'active', note TEXT, created_at TEXT
);
CREATE TABLE recordings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, meet_url TEXT,
 filename TEXT, size_bytes INTEGER, duration_seconds INTEGER, created_at TEXT
);
""")
wallet.create_wallet_schema(db)

source = (ROOT / "app/admin_panel.py").read_text(encoding="utf-8")
node = ast.parse(source)
definitions = {n.name: n for n in node.body if isinstance(n, ast.FunctionDef)}
env = {
    "_db": lambda: db,
    "utcnow": lambda: datetime.now(timezone.utc),
    "datetime": datetime,
    "timezone": timezone,
    "timedelta": timedelta,
    "secrets": secrets,
    "_parse_dt": lambda value: datetime.fromisoformat(value) if value else None,
    "wallet_balance": wallet.balance,
    "create_wallet_schema": wallet.create_wallet_schema,
    "add_entry": wallet.add_entry,
    "has_wallet_history": wallet.has_wallet_history,
    "TRIAL_CREDIT_MINUTES": 60,
    "TRIAL_CREDIT_SECONDS": 3600,
    "PUBLIC_PLAN_CODES": policy.PUBLIC_PLAN_CODES,
    "PUBLIC_PLANS": policy.PUBLIC_PLANS,
    "PLANS": policy.PLANS,
    "plan_quota_seconds": policy.plan_quota_seconds,
    "PAID_SALES_MAX_ACTIVE_USERS": 12,
    "PAID_SALES_MAX_SOLD_HOURS": 60,
}


def extract(name):
    function = definitions[name]
    snippet = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(snippet, "app/admin_panel.py", "exec"), env)


for name in (
    "touch_user", "recording_credit_info", "subscription_info",
    "_active_legacy_subscription", "is_premium", "was_premium_at",
    "free_recording_entitlement", "paid_recording_entitlement",
    "record_recording", "paid_sales_capacity", "credit_purchase",
):
    extract(name)

touch = env["touch_user"]
balance = env["recording_credit_info"]
record = env["record_recording"]
is_premium = env["is_premium"]

assert touch("first", "newhandle", "New", "User") is True
assert balance("first")["remaining_seconds"] == 3600
assert env["free_recording_entitlement"]("first")["allowed"]
assert not is_premium("first"), "trial-only users must not consume premium worker slots"
assert touch("first", "newhandle", "New", "User") is False
assert db.execute(
    "SELECT COUNT(*) FROM credit_entries WHERE telegram_id=? AND kind='trial'", ("first",)
).fetchone()[0] == 1

capacity = env["paid_sales_capacity"]("basic", "first")
assert capacity["active_users"] == 0, "free sign-ups must not fill the 12 paid-member cap"
assert capacity["allowed"] is True
assert env["was_premium_at"]("first", (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()) is False

record("first", "https://meet.google.com/abc-defg-hij", "trial-1.webm", 1000, 1800)
assert balance("first")["remaining_seconds"] == 1800, "trial session consumes real minutes"
record("first", "https://meet.google.com/abc-defg-hij", "trial-1.webm", 1000, 1800)
assert balance("first")["remaining_seconds"] == 1800, "retry must not debit twice"

record("first", "https://meet.google.com/abc-defg-hij", "trial-2.webm", 1000, 3600)
assert balance("first")["signed_balance_seconds"] == -1800, "overrun carries forward"
assert balance("first")["remaining_seconds"] == 0
assert not env["free_recording_entitlement"]("first")["allowed"]
assert not is_premium("first")
assert touch("first") is False, "no renewal of trial credit on subsequent /start"

remaining = env["credit_purchase"]("first", "basic", "paid-001")["remaining_seconds"]
assert remaining == 5400, "purchased time settles a prior gift overrun"
assert env["credit_purchase"]("first", "basic", "paid-001")["remaining_seconds"] == remaining
assert is_premium("first"), "paid balance must allow premium priority"
assert env["paid_sales_capacity"]("basic", "first")["active_users"] == 1

# Historical customers who already made a recording used their old free trial.
now = datetime.now(timezone.utc).isoformat()
db.execute(
    "INSERT INTO users (telegram_id, first_seen, last_seen, total_recordings) VALUES (?, ?, ?, ?)",
    ("legacy-trial", now, now, 1),
)
assert touch("legacy-trial") is False
assert balance("legacy-trial")["remaining_seconds"] == 0

# Existing registered members with zero successful recordings retain eligibility.
db.execute(
    "INSERT INTO users (telegram_id, first_seen, last_seen) VALUES (?, ?, ?)",
    ("existing-unused", now, now),
)
assert touch("existing-unused") is True
assert balance("existing-unused")["remaining_seconds"] == 3600
assert touch("existing-unused") is False

# Zero-minute trial configuration means no promo, not a free unmetered recording.
env["TRIAL_CREDIT_SECONDS"] = 0
assert touch("no-gift") is False
assert balance("no-gift")["remaining_seconds"] == 0

print("TRIAL_UNIFIED_WALLET_BEHAVIOR_TEST_PASS")
