#!/usr/bin/env python3
"""Business-path regression: usage persists as debits, not monthly renewals."""
from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]
admin=(root/"app/admin_panel.py").read_text()
main=(root/"app/main.py").read_text()
wallet=(root/"app/credit_wallet.py").read_text()
for source in (admin,main,wallet):ast.parse(source)
assert 'CREATE TABLE IF NOT EXISTS credit_entries' in wallet
assert 'reference TEXT PRIMARY KEY' in wallet
assert 'seconds_delta BIGINT NOT NULL' in wallet
assert 'ON CONFLICT(reference) DO NOTHING' in wallet
assert 'if duplicate:' in admin
assert 'add_entry(db,str(telegram_id),-max(0,int(duration_seconds))' in admin
assert 'has_wallet_history(db,str(telegram_id))' in admin
assert 'if note.startswith("Zibal receipt ")' in admin, "historical paid subscription callbacks still recognized"
assert 'if not old:' in admin and 'add_entry(db,str(telegram_id),int(seconds),f"zibal:{receipt}","purchase")' in admin
assert 'paid_sales_capacity' in admin and 'SUM(seconds_delta)>0' in admin
assert 'wallet = await asyncio.to_thread(credit_purchase, telegram_id, expected_plan, receipt)' in main
assert 'await asyncio.to_thread(recording_credit_info, str(chat_id))' in main
assert 'No automatic renewals' in main or 'no automatic renewal' in main.lower()
assert 'new 30-day period' not in main[main.index('@app.get("/", response_class=HTMLResponse)'):main.index('@app.get("/privacy", response_class=HTMLResponse)')]
print("BILLING_USAGE_BEHAVIOR_TEST_PASS")
