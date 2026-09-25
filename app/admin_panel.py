import hashlib
import hmac
import html
import os
import sqlite3
import time
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from db_compat import connect_db, is_postgres

router = APIRouter()
DB_PATH = Path(os.environ.get("BEONMEET_DB_PATH", "/data/beonmeet.db"))
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
ADMINUSER = os.environ.get("ADMINUSER", "").strip()
DOMAIN = os.environ.get("DOMAIN", "beonmeet.smarbiz.sbs")

PLANS = {
    "monthly": {"label": "یک ماهه", "months": 1, "price": 198_000},
    "quarterly": {"label": "سه ماهه", "months": 3, "price": 499_000},
    "halfyear": {"label": "شش ماهه", "months": 6, "price": 799_000},
}

PREMIUM_FEATURES = [
    ("کیفیت بالاتر ضبط", "ضبط با کیفیت بالاتر نسبت به پلن رایگان، تا سقف کیفیت واقعی دریافتی از Google Meet", "ready"),
    ("فایل صوتی جداگانه", "خروجی MP3 مستقل بعد از پایان جلسه", "ready"),
    ("متن جلسه", "تبدیل صوت به متن؛ در صداهای ضعیف یا همزمان ممکنه خطا داشته باشه", "provider"),
    ("پیش نویس صورتجلسه", "خلاصه نکات مطرح شده در جلسه؛ ممکنه نیاز به بازبینی داشته باشه", "provider"),
    ("ظرفیت اختصاصی و اولویت ورود", "ورکرهای رزروشده برای پلن ویژه؛ پشت صف کاربران رایگان نمی‌مونه و در صورت نیاز از ظرفیت آزاد رایگان هم استفاده می‌کنه", "ready"),
]


def _db():
    return connect_db(DB_PATH)


def _migrate_sqlite_to_postgres_once() -> None:
    if not is_postgres() or not DB_PATH.exists():
        return

    with _db() as db:
        marker = db.execute(
            "SELECT value FROM system_meta WHERE key=?",
            ("sqlite_migrated",),
        ).fetchone()
        if marker:
            return

    try:
        legacy = sqlite3.connect(DB_PATH, timeout=5)
        legacy.row_factory = sqlite3.Row
    except Exception as exc:
        print("legacy sqlite migration skipped:", repr(exc), flush=True)
        return

    try:
        with _db() as db:
            for row in legacy.execute("SELECT * FROM users"):
                db.execute(
                    """
                    INSERT INTO users
                        (telegram_id, username, first_name, last_name, first_seen, last_seen,
                         total_requests, total_recordings, premium_until, premium_plan)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username=excluded.username,
                        first_name=excluded.first_name,
                        last_name=excluded.last_name,
                        first_seen=excluded.first_seen,
                        last_seen=excluded.last_seen,
                        total_requests=excluded.total_requests,
                        total_recordings=excluded.total_recordings,
                        premium_until=excluded.premium_until,
                        premium_plan=excluded.premium_plan
                    """,
                    tuple(row[k] for k in (
                        "telegram_id", "username", "first_name", "last_name",
                        "first_seen", "last_seen", "total_requests", "total_recordings",
                        "premium_until", "premium_plan",
                    )),
                )

            migrations = [
                (
                    "meeting_requests",
                    ("telegram_id", "meet_url", "mode", "created_at"),
                ),
                (
                    "recordings",
                    ("telegram_id", "meet_url", "filename", "size_bytes", "duration_seconds", "created_at"),
                ),
                (
                    "subscriptions",
                    ("telegram_id", "plan_code", "price_toman", "starts_at", "ends_at", "status", "note", "created_at"),
                ),
            ]
            for table, columns in migrations:
                count = db.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                if int(count or 0) > 0:
                    continue
                placeholders = ",".join(["?"] * len(columns))
                column_sql = ",".join(columns)
                for row in legacy.execute(f"SELECT {column_sql} FROM {table}"):
                    db.execute(
                        f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                        tuple(row[k] for k in columns),
                    )

            for row in legacy.execute("SELECT * FROM payment_intents"):
                db.execute(
                    """
                    INSERT INTO payment_intents
                        (intent, telegram_id, plan_code, amount_toman, status, receipt, created_at, expires_at, paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(intent) DO NOTHING
                    """,
                    tuple(row[k] for k in (
                        "intent", "telegram_id", "plan_code", "amount_toman",
                        "status", "receipt", "created_at", "expires_at", "paid_at",
                    )),
                )

            db.execute(
                """
                INSERT INTO system_meta (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                ("sqlite_migrated", utcnow().isoformat()),
            )
        print("legacy SQLite data migrated to PostgreSQL", flush=True)
    except Exception as exc:
        print("legacy SQLite migration failed:", repr(exc), flush=True)
    finally:
        legacy.close()


def init_db() -> None:
    if is_postgres():
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            total_requests BIGINT NOT NULL DEFAULT 0,
            total_recordings BIGINT NOT NULL DEFAULT 0,
            premium_until TEXT,
            premium_plan TEXT
        );
        CREATE TABLE IF NOT EXISTS meeting_requests (
            id BIGSERIAL PRIMARY KEY,
            telegram_id TEXT NOT NULL,
            meet_url TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'calendar',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recordings (
            id BIGSERIAL PRIMARY KEY,
            telegram_id TEXT NOT NULL,
            meet_url TEXT DEFAULT '',
            filename TEXT DEFAULT '',
            size_bytes BIGINT NOT NULL DEFAULT 0,
            duration_seconds BIGINT NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id BIGSERIAL PRIMARY KEY,
            telegram_id TEXT NOT NULL,
            plan_code TEXT NOT NULL,
            price_toman BIGINT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payment_intents (
            intent TEXT PRIMARY KEY,
            telegram_id TEXT NOT NULL,
            plan_code TEXT NOT NULL,
            amount_toman BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            receipt TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            paid_at TEXT
        );
        CREATE TABLE IF NOT EXISTS system_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
        CREATE INDEX IF NOT EXISTS idx_requests_created_at ON meeting_requests(created_at);
        CREATE INDEX IF NOT EXISTS idx_recordings_created_at ON recordings(created_at);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_telegram ON subscriptions(telegram_id);
        """
        with _db() as db:
            db.executescript(schema)
        _migrate_sqlite_to_postgres_once()
        return

    with _db() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                total_requests INTEGER NOT NULL DEFAULT 0,
                total_recordings INTEGER NOT NULL DEFAULT 0,
                premium_until TEXT,
                premium_plan TEXT
            );
            CREATE TABLE IF NOT EXISTS meeting_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT NOT NULL,
                meet_url TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'calendar',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT NOT NULL,
                meet_url TEXT DEFAULT '',
                filename TEXT DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT NOT NULL,
                plan_code TEXT NOT NULL,
                price_toman INTEGER NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payment_intents (
                intent TEXT PRIMARY KEY,
                telegram_id TEXT NOT NULL,
                plan_code TEXT NOT NULL,
                amount_toman INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                receipt TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                paid_at TEXT
            );
            """
        )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def touch_user(telegram_id: str, username: str = "", first_name: str = "", last_name: str = "") -> None:
    now = utcnow().isoformat()
    with _db() as db:
        db.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen
            """,
            (str(telegram_id), username or "", first_name or "", last_name or "", now, now),
        )


def record_request(telegram_id: str, meet_url: str, mode: str) -> None:
    now = utcnow().isoformat()
    with _db() as db:
        db.execute(
            "INSERT INTO meeting_requests (telegram_id, meet_url, mode, created_at) VALUES (?, ?, ?, ?)",
            (str(telegram_id), meet_url, mode, now),
        )
        db.execute(
            "UPDATE users SET total_requests = total_requests + 1, last_seen=? WHERE telegram_id=?",
            (now, str(telegram_id)),
        )


def record_recording(telegram_id: str, meet_url: str, filename: str, size_bytes: int, duration_seconds: int) -> None:
    now = utcnow().isoformat()
    with _db() as db:
        db.execute(
            """
            INSERT INTO recordings (telegram_id, meet_url, filename, size_bytes, duration_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(telegram_id), meet_url or "", filename or "", int(size_bytes or 0), int(duration_seconds or 0), now),
        )
        db.execute(
            "UPDATE users SET total_recordings = total_recordings + 1, last_seen=? WHERE telegram_id=?",
            (now, str(telegram_id)),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def is_premium(telegram_id: str) -> bool:
    with _db() as db:
        row = db.execute("SELECT premium_until FROM users WHERE telegram_id=?", (str(telegram_id),)).fetchone()
    until = _parse_dt(row["premium_until"]) if row else None
    return bool(until and until > utcnow())


def subscription_info(telegram_id: str) -> dict:
    with _db() as db:
        row = db.execute(
            "SELECT premium_until, premium_plan FROM users WHERE telegram_id=?",
            (str(telegram_id),),
        ).fetchone()
    if not row:
        return {"premium": False, "until": None, "plan": None}
    until = _parse_dt(row["premium_until"])
    return {
        "premium": bool(until and until > utcnow()),
        "until": until,
        "plan": row["premium_plan"],
    }


def activate_subscription(telegram_id: str, plan_code: str, note: str = "") -> datetime:
    if plan_code not in PLANS:
        raise ValueError("invalid plan")
    plan = PLANS[plan_code]
    now = utcnow()
    with _db() as db:
        row = db.execute("SELECT premium_until FROM users WHERE telegram_id=?", (str(telegram_id),)).fetchone()
        current = _parse_dt(row["premium_until"]) if row else None
        start = current if current and current > now else now
        # Calendar-month exactness is not necessary for entitlement; 30-day months keep renewals predictable.
        end = start + timedelta(days=30 * int(plan["months"]))
        db.execute(
            "UPDATE users SET premium_until=?, premium_plan=? WHERE telegram_id=?",
            (end.isoformat(), plan_code, str(telegram_id)),
        )
        db.execute(
            """
            INSERT INTO subscriptions
                (telegram_id, plan_code, price_toman, starts_at, ends_at, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (str(telegram_id), plan_code, int(plan["price"]), start.isoformat(), end.isoformat(), note, now.isoformat()),
        )
    return end


def deactivate_subscription(telegram_id: str) -> None:
    now = utcnow().isoformat()
    with _db() as db:
        db.execute(
            "UPDATE users SET premium_until=NULL, premium_plan=NULL WHERE telegram_id=?",
            (str(telegram_id),),
        )
        db.execute(
            "UPDATE subscriptions SET status='cancelled' WHERE telegram_id=? AND status='active'",
            (str(telegram_id),),
        )


def create_payment_intent(telegram_id: str, plan_code: str) -> dict:
    if plan_code not in PLANS:
        raise ValueError("invalid plan")
    plan = PLANS[plan_code]
    now = utcnow()
    intent = secrets.token_urlsafe(24)
    expires = now + timedelta(minutes=30)
    with _db() as db:
        db.execute(
            """INSERT INTO payment_intents
               (intent, telegram_id, plan_code, amount_toman, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (intent, str(telegram_id), plan_code, int(plan["price"]), now.isoformat(), expires.isoformat()),
        )
    return {
        "intent": intent,
        "telegram_id": str(telegram_id),
        "plan": plan_code,
        "amount_toman": int(plan["price"]),
        "label": f"پلن ویژه BeOnMeet، {plan['label']}",
        "expires_at": expires,
    }


def get_payment_intent(intent: str) -> dict | None:
    with _db() as db:
        row = db.execute("SELECT * FROM payment_intents WHERE intent=? LIMIT 1", (str(intent),)).fetchone()
    if not row:
        return None
    data = dict(row)
    expires = _parse_dt(data.get("expires_at"))
    if data.get("status") == "pending" and expires and expires <= utcnow():
        with _db() as db:
            db.execute("UPDATE payment_intents SET status='expired' WHERE intent=? AND status='pending'", (str(intent),))
        data["status"] = "expired"
    return data


def mark_payment_paid(intent: str, receipt: str) -> dict | None:
    now = utcnow().isoformat()
    with _db() as db:
        row = db.execute("SELECT * FROM payment_intents WHERE intent=? LIMIT 1", (str(intent),)).fetchone()
        if not row:
            return None
        if row["status"] == "paid":
            return dict(row)
        db.execute(
            "UPDATE payment_intents SET status='paid', receipt=?, paid_at=? WHERE intent=?",
            (str(receipt), now, str(intent)),
        )
        fresh = db.execute("SELECT * FROM payment_intents WHERE intent=? LIMIT 1", (str(intent),)).fetchone()
    return dict(fresh) if fresh else None


def make_admin_login_url() -> str:
    exp = int(time.time()) + 900
    payload = f"admin:{ADMINUSER}:{exp}"
    sig = hmac.new(INTERNAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"https://{DOMAIN}/admin/login?exp={exp}&sig={sig}"


def _valid_token(exp: str, sig: str) -> bool:
    try:
        exp_i = int(exp)
    except Exception:
        return False
    if exp_i < int(time.time()) or exp_i > int(time.time()) + 86400:
        return False
    payload = f"admin:{ADMINUSER}:{exp_i}"
    expected = hmac.new(INTERNAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _admin_ok(request: Request) -> bool:
    token = request.cookies.get("beonmeet_admin", "")
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    return _valid_token(exp, sig)


def _require_admin(request: Request) -> None:
    if not _admin_ok(request):
        raise HTTPException(status_code=401, detail="برای ورود، دستور /admin را داخل ربات بفرست.")


def _money(value: int) -> str:
    return f"{int(value):,}".replace(",", "٬")


def _fa_date(value: str | None) -> str:
    dt = _parse_dt(value)
    if not dt:
        return "ندارد"
    return dt.astimezone().strftime("%Y/%m/%d  %H:%M")


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _layout(title: str, body: str, active: str = "dashboard") -> str:
    nav = [
        ("dashboard", "/admin", "داشبورد", "⌂"),
        ("users", "/admin/users", "کاربران", "◉"),
        ("recordings", "/admin/recordings", "ضبط ها", "◍"),
        ("subscriptions", "/admin/subscriptions", "اشتراک ها", "◆"),
        ("plans", "/admin/plans", "پلن ویژه", "✦"),
    ]
    nav_html = "".join(
        f'<a class="nav {"active" if key==active else ""}" href="{href}"><span>{icon}</span>{label}</a>'
        for key, href, label, icon in nav
    )
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · BeOnMeet</title>
<style>
:root{{--bg:#080a12;--panel:#10131f;--panel2:#151927;--text:#f7f8ff;--muted:#8e96aa;--line:#242a3c;--a:#8c5cff;--b:#3bd5ff;--good:#48e5a5;--warn:#ffbe55;--bad:#ff6685}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(900px 500px at 80% -10%,#3a1f7b55,transparent),radial-gradient(700px 450px at 10% 100%,#0f6a8550,transparent),var(--bg);color:var(--text);font-family:Tahoma,Arial,sans-serif;min-height:100vh}}
.shell{{display:grid;grid-template-columns:250px 1fr;min-height:100vh}} aside{{background:#0b0e17cc;border-left:1px solid var(--line);padding:24px 18px;backdrop-filter:blur(22px);position:sticky;top:0;height:100vh}}
.brand{{display:flex;align-items:center;gap:12px;font-weight:800;font-size:20px;margin:2px 8px 34px}} .logo{{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,var(--a),var(--b));display:grid;place-items:center;box-shadow:0 12px 38px #7c56ff55}} .logo:after{{content:"B";font-size:22px}}
.nav{{display:flex;gap:12px;align-items:center;padding:13px 14px;margin:6px 0;color:#9fa8bd;text-decoration:none;border-radius:13px;transition:.2s}} .nav:hover,.nav.active{{color:white;background:linear-gradient(90deg,#8c5cff22,#3bd5ff0f);box-shadow:inset -2px 0 var(--a)}} .nav span{{width:22px;color:#a98aff}}
.side-foot{{position:absolute;bottom:24px;right:18px;left:18px;color:#697289;font-size:12px;line-height:1.8}}
main{{padding:34px 38px 60px;max-width:1500px;width:100%}} .top{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:28px}} h1{{margin:0;font-size:28px}} .sub{{color:var(--muted);font-size:13px;margin-top:7px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}} .card{{background:linear-gradient(145deg,#151927dd,#0f121ddd);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 18px 55px #0004;backdrop-filter:blur(16px)}} .metric .label{{color:var(--muted);font-size:12px}} .metric .num{{font-size:28px;font-weight:900;margin-top:12px}} .metric .hint{{font-size:11px;color:#697289;margin-top:8px}}
.good{{color:var(--good)}} .warn{{color:var(--warn)}} .purple{{color:#b99cff}} .cyan{{color:#73dfff}}
.section{{margin-top:20px}} .section-head{{display:flex;justify-content:space-between;align-items:center;margin:0 2px 12px}} .section-head h2{{font-size:16px;margin:0}} .pill{{padding:7px 11px;border-radius:99px;background:#ffffff0b;border:1px solid var(--line);color:var(--muted);font-size:11px}}
table{{width:100%;border-collapse:collapse}} th{{text-align:right;color:#737d94;font-weight:500;font-size:11px;padding:0 10px 13px}} td{{padding:14px 10px;border-top:1px solid #22283a;font-size:12px;vertical-align:middle}} tr:hover td{{background:#ffffff02}} .user{{display:flex;gap:10px;align-items:center}} .avatar{{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;font-weight:800;background:linear-gradient(135deg,#7856dd,#196f91)}} .muted{{color:var(--muted)}} .badge{{font-size:10px;padding:5px 8px;border-radius:9px;border:1px solid var(--line)}} .premium{{color:#dbc9ff;background:#8c5cff1e;border-color:#7d5bdd66}} .free{{color:#a6afc1;background:#ffffff05}}
.btn{{border:0;border-radius:10px;padding:9px 12px;font:inherit;font-size:11px;cursor:pointer;color:white;background:#ffffff0c;border:1px solid var(--line)}} .btn.primary{{background:linear-gradient(135deg,#7654f5,#4e7dff);border:0}} .btn.danger{{color:#ff9aad;border-color:#ff668544;background:#ff668510}}
form.inline{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}} select,input{{background:#0d1019;color:#eef1ff;border:1px solid var(--line);border-radius:9px;padding:8px 9px;font:inherit;font-size:11px}} .search{{min-width:260px}}
.two{{display:grid;grid-template-columns:1.2fr .8fr;gap:18px}} .chart{{height:180px;display:flex;align-items:flex-end;gap:10px;padding-top:15px}} .barwrap{{flex:1;text-align:center;color:#697289;font-size:10px}} .bar{{background:linear-gradient(180deg,var(--b),var(--a));border-radius:7px 7px 3px 3px;min-height:4px;box-shadow:0 0 22px #8c5cff40;margin-bottom:7px}}
.plan-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} .plan{{position:relative;overflow:hidden}} .plan:before{{content:"";position:absolute;inset:-80px auto auto -80px;width:180px;height:180px;background:#8c5cff22;filter:blur(25px);border-radius:50%}} .price{{font-size:25px;font-weight:900;margin:13px 0 4px}} .feature{{display:flex;gap:9px;padding:9px 0;border-bottom:1px solid #22283a;font-size:12px}} .feature:last-child{{border:0}} .dot{{width:7px;height:7px;margin-top:5px;border-radius:50%;background:var(--good);box-shadow:0 0 12px var(--good)}} .dot.planned{{background:var(--warn);box-shadow:0 0 12px var(--warn)}} .dot.provider{{background:#9c78ff;box-shadow:0 0 12px #9c78ff}}
.empty{{padding:45px;text-align:center;color:var(--muted)}} .alert{{padding:13px 15px;border:1px solid #8c5cff44;background:#8c5cff10;border-radius:12px;color:#cdbdff;font-size:12px;margin-bottom:16px}}
@media(max-width:950px){{.shell{{grid-template-columns:1fr}} aside{{height:auto;position:relative;border:0;padding:16px;display:flex;overflow:auto;gap:6px}} .brand,.side-foot{{display:none}} .nav{{white-space:nowrap;margin:0}} main{{padding:22px 15px}} .grid{{grid-template-columns:repeat(2,1fr)}} .two,.plan-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body><div class="shell"><aside><div class="brand"><div class="logo"></div><div>BeOnMeet<br><small style="color:#697289;font-size:10px">ADMIN CONSOLE</small></div></div>{nav_html}<div class="side-foot">ضبط هوشمند جلسه<br>نسخه مدیریت داخلی</div></aside><main>{body}</main></div></body></html>"""


def _stats():
    with _db() as db:
        users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        premium = db.execute(
            "SELECT COUNT(*) c FROM users WHERE premium_until IS NOT NULL AND premium_until > ?",
            (utcnow().isoformat(),),
        ).fetchone()["c"]
        recordings = db.execute("SELECT COUNT(*) c FROM recordings").fetchone()["c"]
        requests = db.execute("SELECT COUNT(*) c FROM meeting_requests").fetchone()["c"]
        recent = db.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 8").fetchall()
        days = []
        for i in range(6, -1, -1):
            day = (utcnow() - timedelta(days=i)).date().isoformat()
            count = db.execute(
                "SELECT COUNT(*) c FROM meeting_requests WHERE substr(created_at,1,10)=?", (day,)
            ).fetchone()["c"]
            days.append((day[-5:], count))
    return users, premium, recordings, requests, recent, days


@router.get("/admin/login")
async def admin_login(exp: str, sig: str):
    if not _valid_token(exp, sig):
        raise HTTPException(status_code=403, detail="لینک ورود منقضی یا نامعتبره. دوباره /admin رو توی ربات بفرست.")
    session_exp = int(time.time()) + 12 * 3600
    payload = f"admin:{ADMINUSER}:{session_exp}"
    session_sig = hmac.new(INTERNAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    response = RedirectResponse("/admin", status_code=302)
    response.set_cookie(
        "beonmeet_admin",
        f"{session_exp}.{session_sig}",
        max_age=12 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("beonmeet_admin")
    return response


@router.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request):
    _require_admin(request)
    users, premium, recordings, requests, recent, days = _stats()
    max_day = max([x[1] for x in days] + [1])
    bars = "".join(
        f'<div class="barwrap"><div class="bar" style="height:{max(4, int(c/max_day*135))}px"></div>{_esc(d)}<br><b style="color:#cad1e3">{c}</b></div>'
        for d,c in days
    )
    rows = "".join(_user_row(r) for r in recent) or '<tr><td colspan="6" class="empty">هنوز کاربری ثبت نشده</td></tr>'
    body=f"""
    <div class="top"><div><h1>سلام، مدیر 👋</h1><div class="sub">وضعیت BeOnMeet در یک نگاه</div></div><span class="pill">● سیستم آنلاین</span></div>
    <div class="grid">
      <div class="card metric"><div class="label">کل کاربران</div><div class="num cyan">{users}</div><div class="hint">کاربر ثبت شده</div></div>
      <div class="card metric"><div class="label">پلن ویژه فعال</div><div class="num purple">{premium}</div><div class="hint">مشترک فعال</div></div>
      <div class="card metric"><div class="label">درخواست ضبط</div><div class="num">{requests}</div><div class="hint">از ابتدای فعالیت</div></div>
      <div class="card metric"><div class="label">ضبط تکمیل شده</div><div class="num good">{recordings}</div><div class="hint">فایل تحویل شده</div></div>
    </div>
    <div class="two section">
      <div class="card"><div class="section-head"><h2>درخواست های ۷ روز اخیر</h2><span class="pill">Activity</span></div><div class="chart">{bars}</div></div>
      <div class="card"><div class="section-head"><h2>قیمت پلن ویژه</h2><a class="pill" href="/admin/plans" style="text-decoration:none">مدیریت پلن</a></div>
        <div style="display:grid;gap:10px;margin-top:12px">
          <div><span class="muted">یک ماهه</span><b style="float:left">{_money(PLANS["monthly"]["price"])} تومان</b></div>
          <div><span class="muted">سه ماهه</span><b style="float:left">{_money(PLANS["quarterly"]["price"])} تومان</b></div>
          <div><span class="muted">شش ماهه</span><b style="float:left">{_money(PLANS["halfyear"]["price"])} تومان</b></div>
        </div>
      </div>
    </div>
    <div class="card section"><div class="section-head"><h2>کاربران اخیر</h2><a class="pill" href="/admin/users" style="text-decoration:none">همه کاربران</a></div>
      <table><thead><tr><th>کاربر</th><th>پلن</th><th>درخواست</th><th>ضبط</th><th>آخرین فعالیت</th><th>مدیریت</th></tr></thead><tbody>{rows}</tbody></table>
    </div>"""
    return _layout("داشبورد", body, "dashboard")


def _user_row(r) -> str:
    active = bool(r["premium_until"] and (_parse_dt(r["premium_until"]) or utcnow()-timedelta(days=1)) > utcnow())
    name = (f'{r["first_name"]} {r["last_name"]}').strip() or "بدون نام"
    uname = f'@{r["username"]}' if r["username"] else r["telegram_id"]
    plan = '<span class="badge premium">ویژه</span>' if active else '<span class="badge free">رایگان</span>'
    initial = _esc((name[:1] or "U").upper())
    return f"""<tr>
      <td><div class="user"><div class="avatar">{initial}</div><div><b>{_esc(name)}</b><div class="muted">{_esc(uname)}</div></div></div></td>
      <td>{plan}</td><td>{r["total_requests"]}</td><td>{r["total_recordings"]}</td><td class="muted">{_fa_date(r["last_seen"])}</td>
      <td><a class="btn" href="/admin/users/{_esc(r["telegram_id"])}">باز کردن</a></td></tr>"""


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(request: Request, q: str = ""):
    _require_admin(request)
    with _db() as db:
        if q.strip():
            like=f"%{q.strip()}%"
            rows=db.execute(
                """SELECT * FROM users WHERE telegram_id LIKE ? OR username LIKE ? OR first_name LIKE ? OR last_name LIKE ?
                   ORDER BY last_seen DESC LIMIT 250""", (like,like,like,like)
            ).fetchall()
        else:
            rows=db.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 250").fetchall()
    table="".join(_user_row(r) for r in rows) or '<tr><td colspan="6" class="empty">چیزی پیدا نشد</td></tr>'
    body=f"""<div class="top"><div><h1>کاربران</h1><div class="sub">{len(rows)} نتیجه</div></div>
    <form><input class="search" name="q" value="{_esc(q)}" placeholder="نام، یوزرنیم یا Telegram ID"><button class="btn primary">جستجو</button></form></div>
    <div class="card"><table><thead><tr><th>کاربر</th><th>پلن</th><th>درخواست</th><th>ضبط</th><th>آخرین فعالیت</th><th>مدیریت</th></tr></thead><tbody>{table}</tbody></table></div>"""
    return _layout("کاربران", body, "users")


@router.get("/admin/users/{telegram_id}", response_class=HTMLResponse)
async def user_page(request: Request, telegram_id: str):
    _require_admin(request)
    with _db() as db:
        u=db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        subs=db.execute("SELECT * FROM subscriptions WHERE telegram_id=? ORDER BY id DESC LIMIT 10", (telegram_id,)).fetchall()
        recs=db.execute("SELECT * FROM recordings WHERE telegram_id=? ORDER BY id DESC LIMIT 10", (telegram_id,)).fetchall()
    if not u: raise HTTPException(404, "کاربر پیدا نشد")
    active=is_premium(telegram_id)
    name=(f'{u["first_name"]} {u["last_name"]}').strip() or "بدون نام"
    sub_rows="".join(f'<tr><td>{_esc(PLANS.get(s["plan_code"], {"label": s["plan_code"]})["label"])}</td><td>{_money(s["price_toman"])}</td><td>{_fa_date(s["starts_at"])}</td><td>{_fa_date(s["ends_at"])}</td><td>{_esc(s["status"])}</td></tr>' for s in subs) or '<tr><td colspan="5" class="empty">اشتراکی ندارد</td></tr>'
    rec_rows="".join(f'<tr><td>{_fa_date(r["created_at"])}</td><td>{_esc(r["meet_url"])}</td><td>{round(r["size_bytes"]/1024/1024,1)} MB</td><td>{round(r["duration_seconds"]/60,1)} دقیقه</td></tr>' for r in recs) or '<tr><td colspan="4" class="empty">ضبطی ندارد</td></tr>'
    body=f"""<div class="top"><div><h1>{_esc(name)}</h1><div class="sub">{_esc("@"+u["username"] if u["username"] else telegram_id)}</div></div>
      {'<span class="badge premium">پلن ویژه فعال تا '+_fa_date(u["premium_until"])+'</span>' if active else '<span class="badge free">پلن رایگان</span>'}</div>
    <div class="grid">
      <div class="card metric"><div class="label">درخواست ها</div><div class="num">{u["total_requests"]}</div></div>
      <div class="card metric"><div class="label">ضبط ها</div><div class="num">{u["total_recordings"]}</div></div>
      <div class="card metric"><div class="label">اولین ورود</div><div class="num" style="font-size:15px">{_fa_date(u["first_seen"])}</div></div>
      <div class="card metric"><div class="label">آخرین فعالیت</div><div class="num" style="font-size:15px">{_fa_date(u["last_seen"])}</div></div>
    </div>
    <div class="card section"><div class="section-head"><h2>مدیریت اشتراک</h2></div>
      <form class="inline" method="post" action="/admin/users/{_esc(telegram_id)}/activate">
        <select name="plan_code"><option value="monthly">یک ماهه · ۱۹۸٬۰۰۰</option><option value="quarterly">سه ماهه · ۴۹۹٬۰۰۰</option><option value="halfyear">شش ماهه · ۷۹۹٬۰۰۰</option></select>
        <input name="note" placeholder="یادداشت اختیاری">
        <button class="btn primary">فعال کردن / تمدید</button>
      </form>
      {'<form style="margin-top:10px" method="post" action="/admin/users/'+_esc(telegram_id)+'/deactivate"><button class="btn danger">غیرفعال کردن پلن ویژه</button></form>' if active else ''}
    </div>
    <div class="two section"><div class="card"><div class="section-head"><h2>سابقه اشتراک</h2></div><table><thead><tr><th>پلن</th><th>مبلغ</th><th>شروع</th><th>پایان</th><th>وضعیت</th></tr></thead><tbody>{sub_rows}</tbody></table></div>
    <div class="card"><div class="section-head"><h2>ضبط های اخیر</h2></div><table><thead><tr><th>زمان</th><th>Meet</th><th>حجم</th><th>مدت</th></tr></thead><tbody>{rec_rows}</tbody></table></div></div>"""
    return _layout(name, body, "users")


@router.post("/admin/users/{telegram_id}/activate")
async def activate_user(request: Request, telegram_id: str):
    _require_admin(request)
    raw=(await request.body()).decode()
    form=parse_qs(raw)
    plan=(form.get("plan_code") or [""])[0]
    note=(form.get("note") or [""])[0]
    activate_subscription(telegram_id, plan, note)
    return RedirectResponse(f"/admin/users/{telegram_id}", status_code=303)


@router.post("/admin/users/{telegram_id}/deactivate")
async def deactivate_user(request: Request, telegram_id: str):
    _require_admin(request)
    deactivate_subscription(telegram_id)
    return RedirectResponse(f"/admin/users/{telegram_id}", status_code=303)


@router.get("/admin/recordings", response_class=HTMLResponse)
async def recordings_page(request: Request):
    _require_admin(request)
    with _db() as db:
        rows=db.execute("""SELECT r.*,u.username,u.first_name,u.last_name FROM recordings r LEFT JOIN users u ON u.telegram_id=r.telegram_id ORDER BY r.id DESC LIMIT 300""").fetchall()
    trs="".join(f'<tr><td>{_fa_date(r["created_at"])}</td><td>{_esc((str(r["first_name"] or "")+" "+str(r["last_name"] or "")).strip() or r["username"] or r["telegram_id"])}</td><td>{_esc(r["meet_url"])}</td><td>{round(r["duration_seconds"]/60,1)} دقیقه</td><td>{round(r["size_bytes"]/1024/1024,1)} MB</td></tr>' for r in rows) or '<tr><td colspan="5" class="empty">هنوز ضبطی ثبت نشده</td></tr>'
    body=f'<div class="top"><div><h1>ضبط ها</h1><div class="sub">متادیتای فایل ها، بدون نگهداری خود ویدیو روی دیسک</div></div></div><div class="card"><table><thead><tr><th>زمان</th><th>کاربر</th><th>جلسه</th><th>مدت</th><th>حجم</th></tr></thead><tbody>{trs}</tbody></table></div>'
    return _layout("ضبط ها", body, "recordings")


@router.get("/admin/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request):
    _require_admin(request)
    with _db() as db:
        rows=db.execute("""SELECT s.*,u.username,u.first_name,u.last_name FROM subscriptions s LEFT JOIN users u ON u.telegram_id=s.telegram_id ORDER BY s.id DESC LIMIT 300""").fetchall()
    trs="".join(f'<tr><td>{_esc((str(r["first_name"] or "")+" "+str(r["last_name"] or "")).strip() or r["username"] or r["telegram_id"])}</td><td>{_esc(PLANS.get(r["plan_code"], {"label": r["plan_code"]})["label"])}</td><td>{_money(r["price_toman"])} تومان</td><td>{_fa_date(r["starts_at"])}</td><td>{_fa_date(r["ends_at"])}</td><td>{_esc(r["status"])}</td></tr>' for r in rows) or '<tr><td colspan="6" class="empty">هنوز اشتراکی ثبت نشده</td></tr>'
    body=f'<div class="top"><div><h1>اشتراک ها</h1><div class="sub">سابقه فعال سازی و تمدید پلن ویژه</div></div></div><div class="card"><table><thead><tr><th>کاربر</th><th>پلن</th><th>مبلغ</th><th>شروع</th><th>پایان</th><th>وضعیت</th></tr></thead><tbody>{trs}</tbody></table></div>'
    return _layout("اشتراک ها", body, "subscriptions")


@router.get("/admin/plans", response_class=HTMLResponse)
async def plans_page(request: Request):
    _require_admin(request)
    feature_html="".join(
        f'<div class="feature"><span class="dot {status}"></span><div><b>{_esc(name)}</b><div class="muted" style="margin-top:4px">{_esc(desc)}</div></div></div>'
        for name,desc,status in PREMIUM_FEATURES
    )
    body=f"""<div class="top"><div><h1>پلن ویژه</h1><div class="sub">قیمت گذاری و نقشه قابلیت های پولی</div></div><span class="badge premium">Premium</span></div>
    <div class="plan-grid">
      <div class="card plan"><span class="badge premium">یک ماهه</span><div class="price">{_money(PLANS["monthly"]["price"])}</div><div class="muted">تومان · ۳۰ روز</div></div>
      <div class="card plan"><span class="badge premium">سه ماهه</span><div class="price">{_money(PLANS["quarterly"]["price"])}</div><div class="muted">تومان · حدود ۱۶٪ به صرفه تر</div></div>
      <div class="card plan"><span class="badge premium">شش ماهه</span><div class="price">{_money(PLANS["halfyear"]["price"])}</div><div class="muted">تومان · حدود ۳۳٪ به صرفه تر</div></div>
    </div>
    <div class="two section"><div class="card"><div class="section-head"><h2>قابلیت های ویژه</h2><span class="pill">قابل توسعه</span></div>{feature_html}</div>
    <div class="card"><div class="section-head"><h2>پلن رایگان</h2></div>
      <div class="feature"><span class="dot"></span><div><b>ورود خودکار به Google Meet</b><div class="muted">از طریق لینک و Calendar</div></div></div>
      <div class="feature"><span class="dot"></span><div><b>ضبط کامل جلسه</b><div class="muted">کیفیت استاندارد</div></div></div>
      <div class="feature"><span class="dot"></span><div><b>ارسال در تلگرام</b><div class="muted">مستقیم برای درخواست دهنده</div></div></div>
      <div class="alert" style="margin-top:15px">پرداخت آنلاین زیبال از مسیر HamoonCloud برای خرید کاربرها در حال استفاده است. فعال سازی دستی هم همچنان از صفحه کاربر در دسترسه.</div>
    </div></div>"""
    return _layout("پلن ویژه", body, "plans")
