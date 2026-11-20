#!/usr/bin/env python3
"""Trial recording is a finite non-expiring wallet balance, never a separate count."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")
WALLET = (ROOT / "app" / "credit_wallet.py").read_text(encoding="utf-8")
I18N = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")
for source in (MAIN, ADMIN, WALLET, I18N):
    ast.parse(source)

for needle in (
    'FREE_TRIAL_MINUTES = max(0, int(os.environ.get("FREE_TRIAL_MINUTES", "60")))',
    'f"welcome:v1:{telegram_id}"',
    '"trial"',
    'not has_wallet_history(db, str(telegram_id))',
    'def free_recording_entitlement',
    '"remaining_seconds": wallet["remaining_seconds"]',
    'return wallet_balance(db,str(telegram_id))["paid_remaining_seconds"] > 0',
):
    assert needle in ADMIN, f"missing time-based free wallet invariant: {needle}"
for needle in (
    "def _pending_free_recordings",
    "async def _free_recording_allowed",
    "remaining > pending * 3600",
    'await send_subscription_offer(chat_id, "free_limit_reached")',
    "if not premium and not await _free_recording_allowed(",
    'if text.strip().lower() == "/now":',
    "include_pending=False",
    'state.setdefault("free_limit_notified", {})',
    '"wallet_trial_included"',
):
    assert needle in MAIN or needle in I18N, f"missing free time controller invariant: {needle}"
assert '"trial"' in WALLET
assert I18N.count('"free_limit_reached"') == 3
assert I18N.count('"wallet_trial_included"') == 3
assert "one free trial recording" not in I18N
assert "۵ ضبط اول رایگان" not in I18N
print("FREE_PLAN_LIMIT_TEST_PASS")
