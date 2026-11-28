"""First-party, per-page-load counters. No accounts, cookies or cross-visit IDs."""
from contextlib import closing
from datetime import datetime, timedelta
from functools import lru_cache
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
CONTROLS = {
    "header_start": "شروع در تلگرام · سربرگ", "hero_start": "شروع در تلگرام · معرفی",
    "nav_how": "روش استفاده · سربرگ", "hero_how": "روش استفاده · معرفی",
    "nav_credits": "ساعت‌های ضبط", "nav_faq": "پرسش‌ها", "brand": "نشان سایت",
    "header_language": "تغییر زبان · سربرگ", "footer_language": "تغییر زبان · پایین صفحه",
    "pricing_terms": "شرایط استفاده · تعرفه‌ها", "footer_terms": "شرایط استفاده · پایین صفحه",
    "footer_privacy": "حریم خصوصی", "skip": "رفتن به محتوای اصلی",
    "faq_1": "پرسش زمان‌بندی", "faq_2": "پرسش خرید ساعت",
    "faq_3": "پرسش مهلت دریافت فایل", "faq_4": "پرسش اطلاعات گوگل",
}
PERIODS = {1: "امروز", 7: "۷ روز", 30: "۳۰ روز", 90: "۹۰ روز"}

def database():
    return Path(os.environ.get("BEONMEET_DATA_DIR", "/data")) / "landing-metrics.sqlite3"

@lru_cache(maxsize=4)
def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db:
        db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS views (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, lang TEXT NOT NULL,
            seconds INTEGER NOT NULL, depth INTEGER NOT NULL
          );
          CREATE INDEX IF NOT EXISTS views_day ON views(day);
          CREATE TABLE IF NOT EXISTS clicks (
            view_id TEXT REFERENCES views(id) ON DELETE CASCADE,
            control TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(view_id,control)
          );
        """)

def validate(data):
    if not isinstance(data, dict) or set(data) != {"id","lang","seconds","depth","clicks"}:
        return False
    clicks = data["clicks"]
    return (isinstance(data["id"], str) and re.fullmatch("[a-f0-9]{32}", data["id"])
            and data["lang"] in ("fa","en")
            and type(data["seconds"]) is int and 0 <= data["seconds"] <= 86400
            and type(data["depth"]) is int and 0 <= data["depth"] <= 100
            and isinstance(clicks, dict)
            and all(k in CONTROLS and type(v) is int and 1 <= v <= 999 for k,v in clicks.items()))

def record(data):
    path = database()
    initialize(path)
    today = datetime.now(TEHRAN).date()
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("DELETE FROM views WHERE day < ?", ((today-timedelta(days=89)).isoformat(),))
        db.execute("""INSERT INTO views VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                   seconds=max(seconds,excluded.seconds), depth=max(depth,excluded.depth)""",
                   (data["id"], today.isoformat(), data["lang"], data["seconds"], data["depth"]))
        db.executemany("""INSERT INTO clicks VALUES(?,?,?) ON CONFLICT(view_id,control)
                       DO UPDATE SET count=max(count,excluded.count)""",
                       [(data["id"], k, v) for k,v in data["clicks"].items()])

def report(days):
    path = database()
    initialize(path)
    today = datetime.now(TEHRAN).date()
    start = (today-timedelta(days=days-1)).isoformat()
    with closing(sqlite3.connect(path, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        summary = dict(db.execute("""SELECT count(*) views, coalesce(sum(seconds),0) seconds,
            count(CASE WHEN depth >= 75 THEN 1 END) deep, count(CASE WHEN lang='fa' THEN 1 END) fa
            FROM views WHERE day>=?""", (start,)).fetchone())
        clicks = dict(db.execute("""SELECT control,sum(count) FROM clicks JOIN views ON views.id=view_id
                           WHERE day>=? GROUP BY control ORDER BY sum(count) DESC""",(start,)))
        starts = db.execute("""SELECT count(DISTINCT view_id) FROM clicks JOIN views ON views.id=view_id
                       WHERE day>=? AND control IN ('header_start','hero_start')""",(start,)).fetchone()[0]
        daily = dict(db.execute("SELECT day,count(*) FROM views WHERE day>=? GROUP BY day",(start,)))
    return summary, clicks, starts, daily

def fa(value):
    return str(value).translate(str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫"))

def report_body(days):
    summary, clicks, starts, daily = report(days)
    views = summary["views"]
    average = round(summary["seconds"] / views) if views else None
    duration = "—" if average is None else f"{fa(average//60)} دقیقه و {fa(average%60)} ثانیه"
    metrics = [("بازدید لندینگ",fa(f"{views:,}")),("کلیک روی دکمه‌ها و پیوندها",fa(f"{sum(clicks.values()):,}")),
               ("میانگین زمان فعال",duration),("نرخ ورود به تلگرام",fa(f"{100*starts/views:.1f}")+"٪" if views else "—")]
    cards = "".join(f'<article class="card metric"><div class="label">{label}</div><strong class="num">{value}</strong></article>' for label,value in metrics)
    filters = "".join(f'<a class="pill" aria-current="{str(n==days).lower()}" href="?days={n}">{label}</a>' for n,label in PERIODS.items())
    rows = "".join(f"<tr><td>{CONTROLS[key]}</td><td>{fa(count)}</td></tr>" for key,count in clicks.items())
    days_rows = "".join(f'<tr><td><bdi>{fa(day)}</bdi></td><td>{fa(count)}</td></tr>' for day,count in sorted(daily.items(),reverse=True))
    empty = '<tr><td colspan="2">هنوز داده‌ای برای این بازه ثبت نشده است.</td></tr>'
    return f"""<div class="top"><div><h1>آمار لندینگ</h1><p class="sub">بازدید و تعامل با صفحهٔ معرفی BeOnMeet</p></div>
      <nav class="periods" aria-label="بازهٔ زمانی">{filters}</nav></div><div class="grid">{cards}</div>
      <div class="card section"><h2>رفتار بازدیدکننده‌ها</h2><p>{fa(summary['fa'])} بازدید فارسی و {fa(views-summary['fa'])} بازدید انگلیسی.
      در {fa(summary['deep'])} بازدید، کاربر دست‌کم ۷۵٪ صفحه را دیده است.</p>
      <p>هر بار بازشدن لندینگ یک بازدید است. زمان فعال فقط وقتی شمرده می‌شود که صفحه در پیش‌زمینه باشد و در یک دقیقهٔ اخیر فعالیتی دیده شده باشد.
      نرخ ورود به تلگرام سهم بازدیدهایی است که در آن‌ها دست‌کم یک بار روی «شروع در تلگرام» کلیک شده است.</p></div>
      <div class="two section"><section class="card"><h2>کلیک به تفکیک دکمه</h2><table><thead><tr><th>دکمه یا پیوند</th><th>تعداد کلیک</th></tr></thead><tbody>{rows or empty}</tbody></table></section>
      <section class="card"><h2>بازدید روزانه</h2><small>به وقت تهران</small><table><thead><tr><th>تاریخ</th><th>بازدید</th></tr></thead><tbody>{days_rows or empty}</tbody></table></section></div>"""
