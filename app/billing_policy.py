"""Authoritative prepaid recording-hour purchase amounts and legacy plan catalog.

Old basic/pro/business codes remain unchanged for HamoonCloud payment compatibility,
but the user buys permanent additive credits rather than monthly subscriptions.
Legacy subscriptions remain recognized solely for grandfathered customers.
"""
from __future__ import annotations

PUBLIC_PLAN_CODES = ("basic", "pro", "business")
PUBLIC_PLANS = {
    "basic": {"label": "۲ ساعت ضبط", "months": 1, "price": 298_000, "quota_minutes": 120},
    "pro": {"label": "۶ ساعت ضبط", "months": 1, "price": 498_000, "quota_minutes": 360},
    "business": {"label": "۱۵ ساعت ضبط", "months": 1, "price": 998_000, "quota_minutes": 900},
}
LEGACY_PLANS = {
    "monthly": {"label": "یک ماهه (قدیمی)", "months": 1, "price": 198_000, "quota_minutes": None},
    "quarterly": {"label": "سه ماهه (قدیمی)", "months": 3, "price": 499_000, "quota_minutes": None},
    "halfyear": {"label": "شش ماهه (قدیمی)", "months": 6, "price": 799_000, "quota_minutes": None},
}
PLANS = {**LEGACY_PLANS, **PUBLIC_PLANS}


def plan_quota_seconds(code: str) -> int | None:
    plan = PLANS.get(str(code or ""))
    if not plan:
        return 0
    minutes = plan.get("quota_minutes")
    return None if minutes is None else max(0, int(minutes)) * 60


def remaining_seconds(code: str, used_seconds: int) -> int | None:
    limit = plan_quota_seconds(code)
    return None if limit is None else max(0, limit - max(0, int(used_seconds or 0)))


def plan_description(code: str) -> str:
    plan = PLANS.get(code) or {}
    quota = plan.get("quota_minutes")
    hours = (int(quota) / 60) if quota is not None else None
    if not plan:
        return "نامشخص"
    if hours is None:
        return f"{plan['label']} (اشتراک قبلی)"
    display_hours = int(hours) if float(hours).is_integer() else hours
    return f"{display_hours} ساعت اعتبار ضبط بدون انقضا"
