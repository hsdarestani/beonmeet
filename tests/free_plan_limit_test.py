#!/usr/bin/env python3
"""Static invariants for wallet-based introductory free recording minutes."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
main=(root/"app/main.py").read_text(encoding="utf-8")
admin=(root/"app/admin_panel.py").read_text(encoding="utf-8")
wallet=(root/"app/credit_wallet.py").read_text(encoding="utf-8")
i18n=(root/"app/i18n.py").read_text(encoding="utf-8")
for needle in (
    'FREE_TRIAL_MINUTES = max(0, int(os.environ.get("FREE_TRIAL_MINUTES", "30")))',
    'and not has_wallet_history(db, str(telegram_id))',
    'f"trial:{telegram_id}", "trial"',
    'def free_recording_entitlement',
    '"remaining_seconds": remaining',
    '"allowed": premium or remaining > 0',
    '"kind IN (\'purchase\',\'migration\',\'admin\')"',
):
    assert needle in admin, needle
for needle in (
    'free_recording_entitlement,',
    'async def _free_recording_allowed',
    'pending == 0',
    'remaining > 0',
    'await send_subscription_offer(chat_id, "free_limit_reached")',
    'wallet.get("trial_granted_seconds")',
):
    assert needle in main, needle
assert '"trial"' in wallet
assert i18n.count('"free_limit_reached"') == 3
assert i18n.count('"trial_credit_in_wallet"') == 3
assert 'one free trial recording' not in i18n
print("FREE_PLAN_LIMIT_TEST_PASS")
