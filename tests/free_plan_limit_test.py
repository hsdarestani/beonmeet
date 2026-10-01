#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")
I18N = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")

required_admin = [
    'FREE_RECORDING_LIMIT = max(0, int(os.environ.get("FREE_RECORDING_LIMIT", "5")))',
    'def free_recording_entitlement',
    '"SELECT total_recordings, premium_until FROM users WHERE telegram_id=?"',
    '"remaining": remaining',
    '"allowed": premium or remaining > 0',
]
for needle in required_admin:
    assert needle in ADMIN, f"missing free-plan DB invariant: {needle}"

required_main = [
    'free_recording_entitlement,',
    'def _pending_free_recordings',
    'async def _free_recording_allowed',
    'used + pending < limit',
    'await send_subscription_offer(chat_id, "free_limit_reached")',
    'if not premium and not await _free_recording_allowed(',
    'if text.strip().lower() == "/now":',
    'include_pending=False',
    'state.setdefault("free_limit_notified", {})',
]
for needle in required_main:
    assert needle in MAIN, f"missing free-plan controller invariant: {needle}"

assert I18N.count('"free_limit_reached"') == 3
assert "up to 5 recorded meetings" in I18N
assert "bis zu 5 aufgezeichnete Meetings" in I18N
assert "حداکثر ۵ جلسه" in I18N

print("FREE_PLAN_LIMIT_TEST_PASS")
