#!/usr/bin/env python3
"""Static guards for the unified onboarding trial and purchased-hour wallet."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")
I18N = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")
WALLET = (ROOT / "app" / "credit_wallet.py").read_text(encoding="utf-8")

for source in (MAIN, ADMIN, I18N, WALLET):
    ast.parse(source)

for needle in (
    'TRIAL_CREDIT_MINUTES = max(0, int(os.environ.get("TRIAL_CREDIT_MINUTES", "60")))',
    'def touch_user(',
    'f"trial:onboarding:{user_id}", "trial"',
    'def free_recording_entitlement(',
    '"remaining_seconds": remaining',
    "kind IN ('purchase','migration','admin','refund')",
    "kind!='trial'",
):
    assert needle in ADMIN, f"missing unified credit invariant: {needle}"

for needle in (
    'trial_credited = await asyncio.to_thread(',
    'trial_credit_added',
    'remaining_seconds > pending * 3600',
    'if text.startswith(("/credits", "/balance", "/plans", "/premium")):',
):
    assert needle in MAIN, f"missing controller trial invariant: {needle}"

assert '"trial"' in WALLET, "trial credit must use the wallet ledger"
assert I18N.count('"trial_credit_added"') == 3
assert I18N.count('"wallet_balance"') == 3
assert 'one free trial recording' not in I18N
print("FREE_PLAN_LIMIT_TEST_PASS")
