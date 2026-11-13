#!/usr/bin/env python3
"""Regressions for the November 2026 BeOnMeet advertising plan launch."""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app"
spec = importlib.util.spec_from_file_location("billing_policy", SRC / "billing_policy.py")
assert spec and spec.loader
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

assert policy.PUBLIC_PLAN_CODES == ("basic", "pro", "business")
assert [policy.PUBLIC_PLANS[k]["price"] for k in policy.PUBLIC_PLAN_CODES] == [298_000, 498_000, 998_000]
assert [policy.plan_quota_seconds(k) for k in policy.PUBLIC_PLAN_CODES] == [7200, 21600, 54000]
assert all(policy.PUBLIC_PLANS[k]["months"] == 1 for k in policy.PUBLIC_PLAN_CODES)
assert policy.remaining_seconds("basic", 3600) == 3600
assert policy.remaining_seconds("basic", 7200) == 0
assert policy.remaining_seconds("basic", 9000) == 0
assert policy.remaining_seconds("pro", -10) == 21600
assert policy.remaining_seconds("monthly", 50_000) is None, "Legacy subscribers must keep original terms"
assert "اشتراک قبلی" in policy.plan_description("monthly")

admin = (SRC / "admin_panel.py").read_text(encoding="utf-8")
main = (SRC / "main.py").read_text(encoding="utf-8")
i18n = (SRC / "i18n.py").read_text(encoding="utf-8")
ast.parse(admin)
ast.parse(main)
ast.parse(i18n)

for needle in (
    "def paid_recording_entitlement(",
    "SELECT COALESCE(SUM(duration_seconds), 0) AS total",
    "WHERE telegram_id=? AND created_at>=? AND created_at<?",
    "if duplicate:",
    'return {"premium": True, "allowed": True, "plan": plan',
):
    assert needle in admin, needle
for needle in (
    "for plan_code in PUBLIC_PLAN_CODES:",
    "async def _paid_recording_allowed(",
    "premium and not await _paid_recording_allowed(chat_id, event_id=event_id)",
    "premium and not await _paid_recording_allowed(chat_id, event_id=event_id, notify=False)",
    "reported_seconds = max(0, int(await asyncio.to_thread(_audio_duration_seconds, raw_path)))",
    't(chat_id, "quota_remaining"',
):
    assert needle in main, needle
assert "intents['monthly']" not in main, "Do not offer old duration plans"
assert "ضبط نامحدود در مدت اشتراک" not in i18n
assert "Unlimited recordings while subscribed" not in i18n
assert "Unbegrenzte Aufnahmen während des Abos" not in i18n
assert i18n.count('"plan_basic":') == 3
assert i18n.count('"paid_quota_reached":') == 3
print("BILLING_TIER_TEST_PASS")
