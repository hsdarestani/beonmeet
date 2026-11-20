#!/usr/bin/env python3
"""Execute real SQLite registration, free-minute use, and paid top-up paths."""
from __future__ import annotations

import ast
import importlib.util
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

wallet = load("credit_wallet", ROOT / "app/credit_wallet.py")
policy = load("billing_policy", ROOT / "app/billing_policy.py")
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE users(
    telegram_id TEXT PRIMARY KEY, username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',last_name TEXT DEFAULT '',
    first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,
    total_requests INTEGER DEFAULT 0,total_recordings INTEGER DEFAULT 0,
    premium_until TEXT,premium_plan TEXT);
CREATE TABLE recordings(
    id INTEGER PRIMARY KEY,telegram_id TEXT NOT NULL,meet_url TEXT,
    filename TEXT,size_bytes INTEGER,duration_seconds INTEGER,created_at TEXT);
CREATE TABLE subscriptions(
    id INTEGER PRIMARY KEY, telegram_id TEXT, plan_code TEXT,
    price_toman INTEGER, starts_at TEXT, ends_at TEXT, status TEXT,
    note TEXT, created_at TEXT);
""")
wallet.create_wallet_schema(db)
source = (ROOT / "app/admin_panel.py").read_text()
functions = {n.name:n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
env = {
    "_db": lambda: db,
    "utcnow": lambda: datetime.now(timezone.utc),
    "datetime": datetime, "timezone": timezone, "secrets": secrets,
    "wallet_balance":wallet.balance, "has_wallet_history":wallet.has_wallet_history,
    "add_entry":wallet.add_entry, "plan_quota_seconds":policy.plan_quota_seconds,
    "PUBLIC_PLAN_CODES":policy.PUBLIC_PLAN_CODES,
    "PLANS":policy.PLANS,"PUBLIC_PLANS":policy.PUBLIC_PLANS,
    "TRIAL_CREDIT_SECONDS":1800, "PAID_SALES_MAX_ACTIVE_USERS":12,
    "PAID_SALES_MAX_SOLD_HOURS":60,
    "_active_legacy_subscription":lambda _telegram_id:None,
}
for name in (
    "touch_user","recording_credit_info","is_premium","free_recording_entitlement",
    "record_recording","credit_purchase","paid_sales_capacity",
):
    node=functions[name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 "app/admin_panel.py","exec"),env)

register=env["touch_user"]
balance=env["recording_credit_info"]
record=env["record_recording"]
eligibility=env["free_recording_entitlement"]

# Only one grant is recorded despite repeated Telegram messages.
register("new","abc","A","B")
register("new","abc","A","B")
assert balance("new")["remaining_seconds"]==1800
assert balance("new")["trial_granted_seconds"]==1800
assert db.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='trial'").fetchone()[0]==1
assert eligibility("new")["allowed"] and eligibility("new")["remaining_seconds"]==1800
assert not env["is_premium"]("new"), "trial must not unlock paid pool"
cap=env["paid_sales_capacity"]("basic","new")
assert cap["active_users"]==0 and cap["sold_hours"]==0

# Every successful free recording consumes actual seconds; duplicate delivery
# is ignored and long first-session overrun does NOT create hidden paid debt.
record("new","meet","trial-a.webm",2000,600)
assert balance("new")["remaining_seconds"]==1200
record("new","meet","trial-a.webm",2000,600)
assert balance("new")["remaining_seconds"]==1200
record("new","meet","trial-b.webm",2000,2400)
assert balance("new")["signed_balance_seconds"]==0
assert not eligibility("new")["allowed"]
register("new")
assert balance("new")["remaining_seconds"]==0, "trial must not reappear"

# Purchases add to the SAME wallet without a second grant.
assert env["credit_purchase"]("new","basic","receipt-1")["remaining_seconds"]==7200
assert balance("new")["trial_granted_seconds"]==1800
assert env["is_premium"]("new"), "paid time unlocks paid pool"
assert env["paid_sales_capacity"]("basic","new")["active_users"]==1
record("new","meet","paid.webm",2000,1800)
assert balance("new")["remaining_seconds"]==5400
register("new")
assert balance("new")["remaining_seconds"]==5400

# Existing customer with a historical recording must not be recredited.
now=datetime.now(timezone.utc).isoformat()
db.execute("""INSERT INTO users(telegram_id,first_seen,last_seen,total_recordings)
              VALUES('existing',?,?,1)""",(now,now))
register("existing")
assert balance("existing")["remaining_seconds"]==0
assert balance("existing")["trial_granted_seconds"]==0
print("TRIAL_WALLET_BEHAVIOR_TEST_PASS")
