#!/usr/bin/env python3
"""Prepaid hour sale SKU compatibility and customer-facing no-subscription guarantees."""
import ast
import importlib.util
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("policy",root/"app/billing_policy.py")
policy=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(policy)
assert policy.PUBLIC_PLAN_CODES==("basic","pro","business")
assert [policy.PUBLIC_PLANS[k]["price"] for k in policy.PUBLIC_PLAN_CODES]==[298_000,498_000,998_000]
assert [policy.plan_quota_seconds(k) for k in policy.PUBLIC_PLAN_CODES]==[7200,21600,54000]
assert policy.plan_quota_seconds("monthly") is None, "grandfathered unlimited periods kept"
assert "بدون انقضا" in policy.plan_description("basic")
main=(root/"app/main.py").read_text()
admin=(root/"app/admin_panel.py").read_text()
i18n=(root/"app/i18n.py").read_text()
for src in (main,admin,i18n):ast.parse(src)
assert "credit_purchase, telegram_id, expected_plan, receipt" in main
assert 'if text.startswith(("/credits", "/balance", "/plans", "/premium")):' in main
assert '"command": "credits"' in main and '"command": "plans"' not in main
assert "create_wallet_schema(db)" in admin
assert "migrate_public_subscriptions_to_wallet()" in admin
assert 'f"zibal:{receipt}"' in admin
assert 'f"recording:{telegram_id}:{filename or' in admin
assert 'admin_credit_hours(telegram_id, plan, note)' in admin
assert "No monthly subscriptions or plans" in i18n
assert "اشتراک ماهانه یا پلن نداریم" in i18n
assert "Keine monatlichen Abos oder Tarife" in i18n
assert "Hours never expire" in main
assert "تاریخ انقضا ندارند" in main
for key in ('"wallet_payment_confirmed":','"wallet_balance":','"wallet_empty":'):
    assert i18n.count(key)==3
print("BILLING_TIER_TEST_PASS")
