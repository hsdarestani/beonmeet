"""Authoritative BeOnMeet plan catalog and side-effect-free quota math.

Legacy duration plans remain recognizable for existing subscribers and pending
payment intents. Only PUBLIC_PLAN_CODES may be offered to new customers.
"""
from __future__ import annotations

PUBLIC_PLAN_CODES = ("basic", "pro", "business")
PUBLIC_PLANS = {
    "basic": {"label": "Basic", "months": 1, "price": 298_000, "quota_minutes": 120},
    "pro": {"label": "Pro", "months": 1, "price": 498_000, "quota_minutes": 360},
    "business": {"label": "Business", "months": 1, "price": 998_000, "quota_minutes": 900},
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
    return f"{plan['label']} · {display_hours} ساعت ضبط در ۳۰ روز"
