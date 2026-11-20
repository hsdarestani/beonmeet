#!/usr/bin/env python3
"""Real SQLite execution of prepaid-hour wallet and legacy migration rules."""
from __future__ import annotations

import ast
import importlib.util
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(obj)
    return obj
policy=load_module('billing_policy',ROOT/'app/billing_policy.py')
wallet=load_module('credit_wallet',ROOT/'app/credit_wallet.py')
db=sqlite3.connect(":memory:")
db.row_factory=sqlite3.Row
db.executescript("""
CREATE TABLE users(
 telegram_id TEXT PRIMARY KEY, premium_until TEXT, premium_plan TEXT,
 total_recordings INT DEFAULT 0, last_seen TEXT);
CREATE TABLE subscriptions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, plan_code TEXT,
 price_toman INT, starts_at TEXT, ends_at TEXT,
 status TEXT DEFAULT 'active', note TEXT, created_at TEXT);
CREATE TABLE recordings(
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT, meet_url TEXT,
 filename TEXT, size_bytes INT, duration_seconds INT, created_at TEXT);
""")
wallet.create_wallet_schema(db)
NOW=datetime(2026,11,19,8,tzinfo=timezone.utc)
for user,plan in [("42","basic"),("44","monthly"),("fresh",None)]:
    db.execute("INSERT INTO users(telegram_id,premium_until,premium_plan,total_recordings,last_seen) VALUES(?,?,?,?,?)",
               (user,"2026-12-01T08:00:00+00:00" if plan else None,plan,0,NOW.isoformat()))
for who,plan,start,end in (
    ("42","basic","2026-11-01T08:00:00+00:00","2026-12-01T08:00:00+00:00"),
    ("42","pro","2026-12-01T08:00:00+00:00","2026-12-31T08:00:00+00:00"),
    ("44","monthly","2026-11-01T08:00:00+00:00","2026-12-01T08:00:00+00:00"),
):
    db.execute("""INSERT INTO subscriptions(telegram_id,plan_code,price_toman,starts_at,ends_at,status,note,created_at)
                  VALUES(?,?,?,?,?,'active','prior',?)""",
               (who,plan,policy.PLANS[plan]["price"],start,end,NOW.isoformat()))
db.execute("INSERT INTO recordings(telegram_id,meet_url,filename,size_bytes,duration_seconds,created_at) VALUES(?,?,?,?,?,?)",
           ("42","https://meet.google.com/abc-defg-hij","old.mp4",3000,1800,"2026-11-10T08:00:00+00:00"))
db.commit()

source=(ROOT/'app/admin_panel.py').read_text(encoding='utf-8')
mod=ast.parse(source)
functions={n.name:n for n in mod.body if isinstance(n,ast.FunctionDef)}
env={
    "_db":lambda:db, "utcnow":lambda:NOW, "datetime":datetime, "timezone":timezone,
    "timedelta":timedelta,"_parse_dt":lambda s:datetime.fromisoformat(s) if s else None,
    "secrets":secrets,"wallet_balance":wallet.balance,
    "create_wallet_schema":wallet.create_wallet_schema,
    "add_entry":wallet.add_entry,"has_wallet_history":wallet.has_wallet_history,
    "plan_quota_seconds":policy.plan_quota_seconds,"PUBLIC_PLAN_CODES":policy.PUBLIC_PLAN_CODES,
    "PUBLIC_PLANS":policy.PUBLIC_PLANS,"PLANS":policy.PLANS,
    "PAID_SALES_MAX_ACTIVE_USERS":12,"PAID_SALES_MAX_SOLD_HOURS":60,
    "FREE_RECORDING_LIMIT":1,
}
def extract(name):
    node=functions[name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 "app/admin_panel.py","exec"),env)
for name in ("migrate_public_subscriptions_to_wallet","recording_credit_info","subscription_info",
             "_active_legacy_subscription","paid_recording_entitlement","is_premium",
             "credit_purchase","admin_credit_hours","paid_sales_capacity",
             "record_recording","free_recording_entitlement"):
    extract(name)

migrate=env["migrate_public_subscriptions_to_wallet"]
migrate()
assert env["recording_credit_info"]("42")["remaining_seconds"]==int(1.5*3600)+6*3600
assert db.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='migration'").fetchone()[0]==2
migrate()
assert db.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='migration'").fetchone()[0]==2, "idempotent migration"
assert env["is_premium"]("42")
assert env["is_premium"]("44"), "legacy unlimited subscriber must remain entitled"
assert not env["is_premium"]("fresh")

def purchase(uid,plan,receipt):
    return env["credit_purchase"](uid,plan,receipt)["remaining_seconds"]
assert purchase("fresh","basic","receipt-101")==7200
assert purchase("fresh","basic","receipt-102")==14400, "second purchase must add immediately"
assert purchase("fresh","basic","receipt-102")==14400, "duplicate payment must not double-credit"
assert env["is_premium"]("fresh")
assert env["paid_recording_entitlement"]("fresh")["remaining_seconds"]==14400
env["record_recording"]("fresh","https://meet.google.com/abc-defg-hij","one.mp4",1000,5400)
assert env["recording_credit_info"]("fresh")["remaining_seconds"]==9000
env["record_recording"]("fresh","https://meet.google.com/abc-defg-hij","one.mp4",1000,5400)
assert env["recording_credit_info"]("fresh")["remaining_seconds"]==9000, "delivery retry must not debit again"
env["record_recording"]("fresh","https://meet.google.com/abc-defg-hij","over.mp4",1000,12600)
assert env["recording_credit_info"]("fresh")["remaining_seconds"]==0
assert env["recording_credit_info"]("fresh")["signed_balance_seconds"]==-3600
assert not env["is_premium"]("fresh")
assert purchase("fresh","pro","receipt-103")==18000, "future purchase first settles overrun"
assert purchase("fresh","pro","receipt-103")==18000, "retry stable"
assert env["paid_recording_entitlement"]("fresh")["remaining_seconds"]==18000
assert env["paid_sales_capacity"]("basic","fresh")["allowed"] is True

assert purchase("44","basic","receipt-104")==7200
env["record_recording"]("44","https://meet.google.com/abc-defg-hij","legacy-unmetered.mp4",1000,1800)
assert env["recording_credit_info"]("44")["remaining_seconds"]==7200, "legacy rights until expiry"
assert env["paid_recording_entitlement"]("44")["remaining_seconds"] is None
assert wallet.balance(db,"unknown")["remaining_seconds"]==0
assert env["free_recording_entitlement"]("fresh")["premium"], "purchased hours share one wallet"
assert env["free_recording_entitlement"]("fresh")["remaining_seconds"]==18000
print("PREPAID_HOUR_WALLET_BEHAVIOR_TEST_PASS")
