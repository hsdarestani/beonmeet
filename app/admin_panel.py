import asyncio
import hashlib
import json
import hmac
import html
import os
import sqlite3
import time
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from db_compat import connect_db, is_postgres
from state_store import DurableStateStore

router = APIRouter()
DB_PATH = Path(os.environ.get("BEONMEET_DB_PATH", "/data/beonmeet.db"))
DATA_DIR = Path(os.environ.get("BEONMEET_DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "state.json"
USER_TOKEN_DIR = DATA_DIR / "google-tokens"
ADMIN_STATE_STORE = DurableStateStore(STATE_FILE)
PERSONAL_CALENDAR_SCOPES = {
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
}
_GOOGLE_ACCOUNT_CACHE: dict[str, tuple[float, dict]] = {}
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
ADMINUSER = os.environ.get("ADMINUSER", "").strip()
DOMAIN = os.environ.get("DOMAIN", "beonmeet.smarbiz.sbs")
FREE_RECORDING_LIMIT = max(0, int(os.environ.get("FREE_RECORDING_LIMIT", "5")))

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


def _controller_state() -> dict:
    loaded, _source = ADMIN_STATE_STORE.load()
    return loaded if isinstance(loaded, dict) else {}


def _personal_token_ids() -> set[str]:
    if not USER_TOKEN_DIR.exists():
        return set()
    return {
        path.stem
        for path in USER_TOKEN_DIR.glob("*.json")
        if path.stem.lstrip("-").isdigit()
    }


def _google_account_info(telegram_id: str) -> dict:
    """Return safe admin metadata for one personal Google Calendar connection.

    The token itself is never returned. Existing users are resolved through the
    primary Calendar resource, whose id is normally the connected Google account
    email. Results are cached briefly so opening the admin page does not hammer
    Google APIs.
    """
    chat_id = str(telegram_id or "").strip()
    now = time.time()
    cached = _GOOGLE_ACCOUNT_CACHE.get(chat_id)
    if cached and now - cached[0] < 300:
        return dict(cached[1])

    info = {
        "connected": False,
        "scope_ready": False,
        "email": "",
        "token_updated_at": None,
        "error": "",
    }
    if not chat_id.lstrip("-").isdigit():
        info["error"] = "Telegram ID نامعتبر"
        return info

    token_path = USER_TOKEN_DIR / f"{chat_id}.json"
    if not token_path.exists():
        info["error"] = "Google Calendar متصل نیست"
        _GOOGLE_ACCOUNT_CACHE[chat_id] = (now, dict(info))
        return info

    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
        granted = set(payload.get("scopes") or [])
        info["scope_ready"] = PERSONAL_CALENDAR_SCOPES.issubset(granted)
        info["token_updated_at"] = datetime.fromtimestamp(
            token_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()

        creds = Credentials.from_authorized_user_file(str(token_path))
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            info["token_updated_at"] = datetime.now(timezone.utc).isoformat()

        email = str(payload.get("account") or "").strip()
        if not email or "@" not in email:
            # The personal OAuth flow grants calendar.calendarlist.readonly.
            # Resolve the account from the primary CalendarList entry instead of
            # calendars/primary, which may require a different Calendar scope.
            page_token = None
            while True:
                params = {
                    "maxResults": 250,
                    "showDeleted": "false",
                    "showHidden": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                response = httpx.get(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers={"Authorization": f"Bearer {creds.token}"},
                    params=params,
                    timeout=6.0,
                )
                response.raise_for_status()
                calendar_list = response.json()
                for calendar in calendar_list.get("items", []) or []:
                    if not calendar.get("primary"):
                        continue
                    primary_id = str(calendar.get("id") or "").strip()
                    summary = str(
                        calendar.get("summaryOverride")
                        or calendar.get("summary")
                        or ""
                    ).strip()
                    if "@" in primary_id:
                        email = primary_id
                    elif "@" in summary:
                        email = summary
                    break
                if email or not calendar_list.get("nextPageToken"):
                    break
                page_token = calendar_list.get("nextPageToken")

        info["email"] = email
        info["connected"] = bool(info["scope_ready"] and creds.valid)
        if not info["scope_ready"]:
            info["error"] = "مجوز کامل Calendar نیاز به اتصال مجدد دارد"
        elif not email:
            info["error"] = "اتصال برقرار است ولی ایمیل از Google برنگشت"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        info["error"] = f"خطا در بررسی Google: HTTP {status}"
    except Exception as exc:
        info["error"] = f"خطا در بررسی Google: {type(exc).__name__}"

    _GOOGLE_ACCOUNT_CACHE[chat_id] = (now, dict(info))
    return info


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


def find_recording_for_artifact(
    filename: str,
    size_bytes: int,
    artifact_created_at: str,
    tolerance_minutes: int = 15,
) -> dict | None:
    """Resolve one recording owner from exact artifact metadata.

    Recovery is deliberately fail-closed: filename and byte size must match and
    exactly one recording must fall inside the narrow creation-time window.
    """
    target = _parse_dt(artifact_created_at)
    if not target:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    with _db() as db:
        rows = db.execute(
            """
            SELECT * FROM recordings
            WHERE filename=? AND size_bytes=?
            ORDER BY id DESC
            LIMIT 50
            """,
            (filename or "", int(size_bytes or 0)),
        ).fetchall()
    matches = []
    tolerance = timedelta(minutes=max(1, int(tolerance_minutes)))
    for row in rows:
        created = _parse_dt(row["created_at"])
        if not created:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if abs(created - target) <= tolerance:
            matches.append(dict(row))
    return matches[0] if len(matches) == 1 else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def free_recording_entitlement(telegram_id: str) -> dict:
    """Return the current lifetime free-recording allowance for one Telegram user."""
    with _db() as db:
        row = db.execute(
            "SELECT total_recordings, premium_until FROM users WHERE telegram_id=?",
            (str(telegram_id),),
        ).fetchone()

    used = int(row["total_recordings"] or 0) if row else 0
    until = _parse_dt(row["premium_until"]) if row else None
    premium = bool(until and until > utcnow())
    remaining = max(0, FREE_RECORDING_LIMIT - used)
    return {
        "premium": premium,
        "used": used,
        "limit": FREE_RECORDING_LIMIT,
        "remaining": remaining,
        "allowed": premium or remaining > 0,
    }


def is_premium(telegram_id: str) -> bool:
    with _db() as db:
        row = db.execute("SELECT premium_until FROM users WHERE telegram_id=?", (str(telegram_id),)).fetchone()
    until = _parse_dt(row["premium_until"]) if row else None
    return bool(until and until > utcnow())


def was_premium_at(telegram_id: str, when_iso: str) -> bool:
    when = _parse_dt(when_iso)
    if not when:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    with _db() as db:
        rows = db.execute(
            "SELECT starts_at, ends_at FROM subscriptions WHERE telegram_id=? ORDER BY id DESC LIMIT 100",
            (str(telegram_id),),
        ).fetchall()
    for row in rows:
        starts = _parse_dt(row["starts_at"])
        ends = _parse_dt(row["ends_at"])
        if not starts or not ends:
            continue
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if starts <= when < ends:
            return True
    return False


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
        ("auto", "/admin/auto-meetings", "همه جلسات", "◎"),
        ("subscriptions", "/admin/subscriptions", "اشتراک ها", "◆"),
        ("plans", "/admin/plans", "پلن ویژه", "✦"),
        ("system", "/admin/system", "سیستم", "◫"),
    ]
    nav_html = "".join(
        f'<a class="nav nav-{key} {"active" if key==active else ""}" href="{href}"><span class="nav-icon">{icon}</span><span class="nav-label">{label}</span></a>'
        for key, href, label, icon in nav
    )
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · BeOnMeet</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Nunito:wght@700;800;900&family=Vazirmatn:wght@400;500;600;700;800;900&display=swap');

:root{{
  --canvas:#f6f8fc;
  --surface:rgba(255,255,255,.74);
  --surface-strong:rgba(255,255,255,.90);
  --surface-soft:rgba(248,250,255,.72);
  --text:#202124;
  --muted:#5f6368;
  --muted-2:#7b8190;
  --line:rgba(60,64,67,.10);
  --line-blue:rgba(66,133,244,.18);
  --blue:#4285F4;
  --blue-dark:#1a73e8;
  --blue-soft:#e8f0fe;
  --red:#EA4335;
  --red-soft:#fce8e6;
  --yellow:#FBBC05;
  --yellow-soft:#fef7e0;
  --green:#34A853;
  --green-soft:#e6f4ea;
  --good:#34A853;
  --warn:#F9AB00;
  --bad:#D93025;
  --shadow-deep:30px 30px 60px rgba(106,117,140,.14),-28px -28px 58px rgba(255,255,255,.96),inset 9px 9px 18px rgba(66,133,244,.035),inset -9px -9px 18px rgba(255,255,255,.82);
  --shadow-card:16px 18px 38px rgba(99,115,148,.15),-10px -10px 24px rgba(255,255,255,.94),inset 5px 5px 11px rgba(66,133,244,.025),inset -5px -5px 11px rgba(255,255,255,.95);
  --shadow-hover:22px 26px 46px rgba(66,133,244,.15),-12px -12px 28px rgba(255,255,255,.98),inset 5px 5px 11px rgba(66,133,244,.035),inset -5px -5px 11px rgba(255,255,255,.96);
  --shadow-button:10px 12px 24px rgba(66,133,244,.28),-7px -7px 16px rgba(255,255,255,.58),inset 3px 3px 8px rgba(255,255,255,.34),inset -4px -4px 8px rgba(18,74,145,.12);
  --shadow-pressed:inset 9px 9px 18px rgba(148,158,181,.18),inset -9px -9px 18px rgba(255,255,255,.96);
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{
  margin:0;
  min-height:100vh;
  overflow-x:hidden;
  color:var(--text);
  background:
    radial-gradient(circle at 12% 8%,rgba(66,133,244,.13),transparent 29rem),
    radial-gradient(circle at 82% 5%,rgba(234,67,53,.10),transparent 24rem),
    radial-gradient(circle at 88% 82%,rgba(52,168,83,.10),transparent 28rem),
    radial-gradient(circle at 8% 88%,rgba(251,188,5,.12),transparent 25rem),
    linear-gradient(145deg,#f8fbff 0%,#f5f7fb 52%,#f9fbff 100%);
  font-family:"Vazirmatn","DM Sans",Tahoma,Arial,sans-serif;
}}
body:before{{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.28) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.22) 1px,transparent 1px);
  background-size:36px 36px;
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.18),transparent 58%);
  z-index:-3;
}}
.clay-ambient{{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:-2}}
.clay-ambient i{{position:absolute;display:block;border-radius:999px;filter:blur(42px);opacity:.17;animation:clayFloat 11s ease-in-out infinite}}
.clay-ambient .blob-blue{{width:36vw;height:36vw;background:var(--blue);right:-12vw;top:7vh}}
.clay-ambient .blob-red{{width:26vw;height:26vw;background:var(--red);left:-7vw;top:14vh;animation-delay:-3s}}
.clay-ambient .blob-yellow{{width:28vw;height:28vw;background:var(--yellow);left:8vw;bottom:-12vw;animation-delay:-6s}}
.clay-ambient .blob-green{{width:32vw;height:32vw;background:var(--green);right:19vw;bottom:-15vw;animation-delay:-8s}}
@keyframes clayFloat{{0%,100%{{transform:translate3d(0,0,0) rotate(0)}}50%{{transform:translate3d(0,-18px,0) rotate(2deg)}}}}

.shell{{display:grid;grid-template-columns:258px minmax(0,1fr);min-height:100vh;direction:ltr}}
aside{{
  direction:rtl;
  position:sticky;
  top:18px;
  align-self:start;
  height:calc(100vh - 36px);
  margin:18px 0 18px 18px;
  padding:24px 17px;
  border:1px solid rgba(255,255,255,.88);
  border-radius:38px;
  background:rgba(255,255,255,.70);
  backdrop-filter:blur(24px) saturate(135%);
  box-shadow:var(--shadow-deep);
  overflow:hidden;
}}
aside:before{{
  content:"";
  position:absolute;
  width:150px;height:150px;border-radius:50%;
  background:rgba(66,133,244,.12);filter:blur(18px);
  top:-72px;left:-62px;pointer-events:none;
}}
.brand{{position:relative;display:flex;align-items:center;gap:13px;font-family:"Nunito","Vazirmatn",sans-serif;font-weight:900;font-size:21px;margin:3px 8px 30px;color:#18233c}}
.logo{{
  width:48px;height:48px;border-radius:18px;display:grid;place-items:center;
  color:#fff;
  background:linear-gradient(145deg,#66a0ff 0%,var(--blue) 58%,#2f6fd8 100%);
  box-shadow:9px 10px 22px rgba(66,133,244,.30),-7px -7px 15px rgba(255,255,255,.70),inset 3px 3px 7px rgba(255,255,255,.34),inset -3px -3px 8px rgba(20,72,147,.17);
}}
.logo:before{{content:"▶";font-size:15px;transform:scaleX(.85)}}
.logo:after{{content:"";position:absolute;width:11px;height:11px;border-radius:50%;background:var(--red);top:0;right:38px;border:3px solid rgba(255,255,255,.88)}}
.brand small{{display:block;color:var(--muted-2)!important;font:700 10px "DM Sans","Vazirmatn",sans-serif;letter-spacing:.12em;margin-top:2px}}
.nav{{
  --nav-accent:var(--blue);
  position:relative;display:flex;gap:12px;align-items:center;min-height:52px;
  padding:12px 14px;margin:7px 0;color:#5f6b82;text-decoration:none;
  border:1px solid transparent;border-radius:20px;font-weight:700;font-size:13px;
  transition:transform .25s ease,box-shadow .25s ease,background .25s ease,color .25s ease,border-color .25s ease;
}}
.nav:nth-of-type(2),.nav-users{{--nav-accent:var(--blue)}}
.nav-recordings{{--nav-accent:var(--red)}}
.nav-auto{{--nav-accent:var(--green)}}
.nav-subscriptions{{--nav-accent:#5f83d9}}
.nav-plans{{--nav-accent:var(--yellow)}}
.nav-system{{--nav-accent:#667085}}
.nav:hover{{transform:translateY(-2px);color:#24324d;background:rgba(255,255,255,.60);border-color:rgba(255,255,255,.92);box-shadow:10px 12px 24px rgba(91,107,139,.12),-7px -7px 16px rgba(255,255,255,.92)}}
.nav.active{{
  color:#0f4fae;
  background:linear-gradient(145deg,rgba(232,240,254,.96),rgba(255,255,255,.88));
  border-color:rgba(66,133,244,.20);
  box-shadow:10px 12px 24px rgba(66,133,244,.15),-8px -8px 18px rgba(255,255,255,.96),inset 3px 3px 8px rgba(66,133,244,.04),inset -3px -3px 8px rgba(255,255,255,.88);
}}
.nav.active:after{{content:"";position:absolute;right:9px;width:5px;height:22px;border-radius:99px;background:var(--nav-accent);box-shadow:0 4px 12px color-mix(in srgb,var(--nav-accent) 45%,transparent)}}
.nav-icon{{
  width:32px;height:32px;display:grid;place-items:center;border-radius:12px;
  color:var(--nav-accent);background:color-mix(in srgb,var(--nav-accent) 10%,white);
  box-shadow:inset 3px 3px 7px rgba(120,132,158,.10),inset -3px -3px 8px rgba(255,255,255,.94);
}}
.side-foot{{position:absolute;bottom:25px;right:22px;left:22px;color:#8a92a2;font-size:11px;line-height:1.85;border-top:1px solid rgba(60,64,67,.08);padding-top:16px}}

main{{direction:rtl;padding:38px 42px 70px;max-width:1650px;width:100%;margin:0 auto}}
.top{{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:30px}}
h1,h2,.num,.price{{font-family:"Nunito","Vazirmatn",sans-serif}}
h1{{margin:0;font-size:30px;line-height:1.15;font-weight:900;letter-spacing:-.025em;color:#18233c}}
.sub{{color:var(--muted);font-size:13px;margin-top:8px}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}}
.card{{
  position:relative;
  background:linear-gradient(145deg,rgba(255,255,255,.86),rgba(246,249,255,.68));
  border:1px solid rgba(255,255,255,.95);
  border-radius:32px;
  padding:23px;
  box-shadow:var(--shadow-card);
  backdrop-filter:blur(22px) saturate(130%);
  transition:transform .35s ease,box-shadow .35s ease,border-color .35s ease;
}}
.card:hover{{transform:translateY(-4px);box-shadow:var(--shadow-hover);border-color:rgba(66,133,244,.16)}}
.metric{{--metric:var(--blue);--metric-soft:var(--blue-soft);min-height:145px;overflow:hidden}}
.metric:nth-child(4n+2){{--metric:var(--red);--metric-soft:var(--red-soft)}}
.metric:nth-child(4n+3){{--metric:var(--yellow);--metric-soft:var(--yellow-soft)}}
.metric:nth-child(4n+4){{--metric:var(--green);--metric-soft:var(--green-soft)}}
.metric:before{{
  content:"";position:absolute;left:20px;top:18px;width:52px;height:52px;border-radius:19px;
  background:linear-gradient(145deg,color-mix(in srgb,var(--metric) 17%,white),color-mix(in srgb,var(--metric) 7%,white));
  box-shadow:8px 10px 22px color-mix(in srgb,var(--metric) 20%,transparent),-6px -6px 14px rgba(255,255,255,.92),inset 3px 3px 7px rgba(255,255,255,.60),inset -3px -3px 7px color-mix(in srgb,var(--metric) 12%,transparent);
}}
.metric:after{{content:"";position:absolute;left:39px;top:37px;width:13px;height:13px;border-radius:50%;background:var(--metric);box-shadow:0 5px 14px color-mix(in srgb,var(--metric) 42%,transparent)}}
.metric .label{{color:var(--muted);font-size:12px;font-weight:650;padding-left:66px}}
.metric .num{{font-size:31px;font-weight:900;margin-top:16px;color:#18233c}}
.metric .hint{{font-size:11px;color:var(--muted-2);margin-top:7px}}
.good{{color:var(--green)!important}} .warn{{color:var(--warn)!important}} .purple{{color:var(--blue)!important}} .cyan{{color:var(--blue)!important}}
.section{{margin-top:22px}}
.section-head{{display:flex;justify-content:space-between;align-items:center;gap:15px;margin:0 2px 16px}}
.section-head h2{{font-size:17px;margin:0;font-weight:900;color:#24324d}}
.pill{{
  display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:7px 12px;
  border-radius:999px;background:rgba(255,255,255,.66);border:1px solid rgba(66,133,244,.12);
  color:#5b6780;font-size:11px;font-weight:700;text-decoration:none;
  box-shadow:inset 4px 4px 9px rgba(127,139,163,.08),inset -4px -4px 9px rgba(255,255,255,.9);
}}
.google-card{{overflow:hidden;border-color:rgba(66,133,244,.17);background:linear-gradient(145deg,rgba(255,255,255,.91),rgba(232,240,254,.66))}}
.google-card:before{{
  content:"";position:absolute;left:-54px;bottom:-82px;width:190px;height:190px;border-radius:50%;
  background:conic-gradient(from 30deg,var(--blue),var(--red),var(--yellow),var(--green),var(--blue));
  filter:blur(34px);opacity:.12;pointer-events:none;
}}
.google-mark{{
  display:inline-grid;place-items:center;width:34px;height:34px;margin-left:9px;border-radius:13px;
  font:900 20px "Nunito",sans-serif;color:var(--blue);background:#fff;
  box-shadow:7px 8px 17px rgba(66,133,244,.14),-5px -5px 12px rgba(255,255,255,.98),inset 2px 2px 5px rgba(66,133,244,.04);
}}
.subscription-card{{overflow:hidden}}
.subscription-card:before{{content:"";position:absolute;width:180px;height:180px;border-radius:50%;background:rgba(251,188,5,.14);filter:blur(35px);left:-75px;top:-80px;pointer-events:none}}
table{{width:100%;border-collapse:separate;border-spacing:0 8px;min-width:680px}}
thead th{{text-align:right;color:#7c8495;font-weight:700;font-size:10px;padding:0 13px 4px}}
tbody td{{
  padding:13px 13px;font-size:12px;vertical-align:middle;background:rgba(248,250,255,.72);
  border-top:1px solid rgba(60,64,67,.055);border-bottom:1px solid rgba(60,64,67,.055);
  transition:background .2s ease,transform .2s ease;
}}
tbody td:first-child{{border-radius:0 17px 17px 0;border-right:1px solid rgba(60,64,67,.055)}}
tbody td:last-child{{border-radius:17px 0 0 17px;border-left:1px solid rgba(60,64,67,.055)}}
tbody tr:hover td{{background:rgba(232,240,254,.65)}}
.user{{display:flex;gap:11px;align-items:center}}
.avatar{{
  width:38px;height:38px;border-radius:15px;display:grid;place-items:center;color:#fff;font-weight:900;
  background:linear-gradient(145deg,#72a8ff,var(--blue));
  box-shadow:7px 8px 17px rgba(66,133,244,.20),-5px -5px 11px rgba(255,255,255,.84),inset 2px 2px 5px rgba(255,255,255,.35),inset -2px -2px 5px rgba(24,86,170,.14);
}}
.muted{{color:var(--muted)}}
.badge{{
  display:inline-flex;align-items:center;gap:5px;min-height:28px;padding:5px 10px;border-radius:999px;
  font-size:10px;font-weight:800;border:1px solid rgba(60,64,67,.08);white-space:nowrap;
}}
.badge.premium,.premium{{color:#146c2e;background:var(--green-soft);border-color:rgba(52,168,83,.20)}}
.badge.free,.free{{color:#697386;background:#f3f5f9;border-color:rgba(60,64,67,.08)}}
.btn{{
  min-height:44px;border:1px solid rgba(60,64,67,.08);border-radius:18px;padding:10px 15px;
  font:700 11px "Vazirmatn","DM Sans",sans-serif;cursor:pointer;color:#48536b;
  background:linear-gradient(145deg,rgba(255,255,255,.96),rgba(241,245,252,.82));
  box-shadow:8px 9px 18px rgba(93,108,139,.13),-6px -6px 14px rgba(255,255,255,.92),inset 2px 2px 5px rgba(255,255,255,.65),inset -2px -2px 6px rgba(105,119,148,.05);
  transition:transform .2s ease,box-shadow .2s ease,color .2s ease;
  text-decoration:none;
}}
.btn:hover{{transform:translateY(-3px);color:#1f54a8;box-shadow:11px 13px 22px rgba(66,133,244,.16),-7px -7px 16px rgba(255,255,255,.96)}}
.btn:active{{transform:scale(.94) translateY(1px);box-shadow:var(--shadow-pressed)}}
.btn.primary{{
  color:#fff;border-color:transparent;background:linear-gradient(145deg,#6da4ff 0%,var(--blue) 55%,#2b71df 100%);
  box-shadow:var(--shadow-button);
}}
.btn.danger{{color:#b3261e;border-color:rgba(234,67,53,.17);background:linear-gradient(145deg,#fff8f7,var(--red-soft));box-shadow:8px 9px 18px rgba(234,67,53,.10),-6px -6px 14px rgba(255,255,255,.92)}}
form.inline{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
select,input{{
  min-height:46px;background:rgba(242,246,252,.88);color:#29344d;border:1px solid rgba(60,64,67,.07);
  border-radius:18px;padding:10px 15px;font:600 11px "Vazirmatn","DM Sans",sans-serif;
  box-shadow:var(--shadow-pressed);outline:none;transition:background .2s ease,box-shadow .2s ease,transform .2s ease;
}}
select:focus,input:focus{{background:#fff;box-shadow:inset 3px 3px 7px rgba(123,137,166,.08),inset -3px -3px 8px rgba(255,255,255,.98),0 0 0 4px rgba(66,133,244,.13)}}
.search{{min-width:285px}}
.two{{display:grid;grid-template-columns:1.15fr .85fr;gap:20px}}
.chart{{height:190px;display:flex;align-items:flex-end;gap:11px;padding:18px 3px 2px}}
.barwrap{{flex:1;text-align:center;color:#8a92a2;font-size:10px}}
.bar{{
  background:linear-gradient(180deg,#76a7fa 0%,var(--blue) 48%,#2f6fd8 100%);
  border-radius:14px 14px 7px 7px;min-height:4px;margin-bottom:9px;
  box-shadow:6px 8px 16px rgba(66,133,244,.18),-4px -4px 10px rgba(255,255,255,.86),inset 2px 2px 5px rgba(255,255,255,.25);
}}
.barwrap:nth-child(4n+2) .bar{{background:linear-gradient(180deg,#f58b82,var(--red))}}
.barwrap:nth-child(4n+3) .bar{{background:linear-gradient(180deg,#ffd45b,var(--yellow))}}
.barwrap:nth-child(4n+4) .bar{{background:linear-gradient(180deg,#74cf8d,var(--green))}}
.plan-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}
.plan{{position:relative;overflow:hidden;min-height:170px}}
.plan:before{{content:"";position:absolute;inset:-85px auto auto -75px;width:185px;height:185px;background:rgba(66,133,244,.13);filter:blur(26px);border-radius:50%}}
.plan:nth-child(2):before{{background:rgba(251,188,5,.14)}} .plan:nth-child(3):before{{background:rgba(52,168,83,.13)}}
.price{{font-size:28px;font-weight:900;margin:16px 0 5px;color:#1f2a44}}
.feature{{display:flex;gap:10px;padding:12px 0;border-bottom:1px solid rgba(60,64,67,.07);font-size:12px}}
.feature:last-child{{border:0}}
.dot{{width:9px;height:9px;margin-top:5px;border-radius:50%;background:var(--green);box-shadow:0 4px 12px rgba(52,168,83,.35)}}
.dot.planned{{background:var(--yellow);box-shadow:0 4px 12px rgba(251,188,5,.35)}}
.dot.provider{{background:var(--blue);box-shadow:0 4px 12px rgba(66,133,244,.35)}}
.empty{{padding:48px;text-align:center;color:var(--muted)}}
.alert{{padding:14px 16px;border:1px solid rgba(251,188,5,.20);background:var(--yellow-soft);border-radius:20px;color:#765b00;font-size:12px;margin-bottom:17px;box-shadow:inset 3px 3px 8px rgba(251,188,5,.05)}}
.card a:not(.btn):not(.pill){{color:var(--blue-dark)}}
.card:has(table){{overflow-x:auto}}
a:focus-visible,.btn:focus-visible,input:focus-visible,select:focus-visible{{outline:none;box-shadow:0 0 0 4px rgba(66,133,244,.18)}}

@media(max-width:1180px){{
  .shell{{grid-template-columns:220px minmax(0,1fr)}} main{{padding:30px 26px 60px}} .grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}
}}
@media(max-width:820px){{
  .shell{{grid-template-columns:1fr;display:block}}
  aside{{height:auto;position:sticky;top:0;z-index:20;margin:0;border-radius:0 0 28px 28px;padding:12px 12px;display:flex;align-items:center;gap:7px;overflow-x:auto}}
  .brand,.side-foot{{display:none}} .nav{{white-space:nowrap;margin:0;min-height:46px;padding:8px 11px;border-radius:16px}} .nav-icon{{width:29px;height:29px}}
  main{{padding:26px 14px 54px}} .top{{align-items:flex-start;flex-direction:column}} .grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
  .two,.plan-grid{{grid-template-columns:1fr}} .card{{border-radius:26px;padding:18px}} .search{{min-width:min(100%,280px)}} form.inline{{width:100%}} select,input{{max-width:100%}}
}}
@media(max-width:540px){{
  h1{{font-size:25px}} .grid{{grid-template-columns:1fr}} .metric{{min-height:130px}} .card{{border-radius:24px}} .top form{{width:100%}} .top .search{{width:100%}} .btn{{min-height:46px}} .section-head{{align-items:flex-start;flex-direction:column}}
}}
@media(prefers-reduced-motion:reduce){{*,*:before,*:after{{animation:none!important;transition:none!important;scroll-behavior:auto!important}}}}
</style>
</head>
<body>
<div class="clay-ambient" aria-hidden="true"><i class="blob-blue"></i><i class="blob-red"></i><i class="blob-yellow"></i><i class="blob-green"></i></div>
<div class="shell"><aside><div class="brand"><div class="logo"></div><div>BeOnMeet<br><small>ADMIN CONSOLE</small></div></div>{nav_html}<div class="side-foot">ضبط هوشمند جلسه<br>پنل مدیریت داخلی</div></aside><main>{body}</main></div>
</body></html>"""


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
    controller_state = _controller_state()
    auto_enabled = bool(controller_state.get("auto_join_all", {}).get(str(telegram_id)))
    google_info = await asyncio.to_thread(_google_account_info, str(telegram_id))
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
    <div class="card section google-card">
      <div class="section-head"><h2><span class="google-mark">G</span>Google Calendar و همه جلسات</h2><a class="pill" href="/admin/auto-meetings">نمایش همه اتصال ها</a></div>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px">
        <div><div class="muted">همه جلسات</div><div style="margin-top:7px">{'<span class="badge premium">روشن</span>' if auto_enabled else '<span class="badge free">خاموش</span>'}</div></div>
        <div><div class="muted">ایمیل Google متصل</div><b style="display:block;margin-top:7px;direction:ltr;text-align:right">{_esc(google_info.get("email") or "مشخص نشده")}</b></div>
        <div><div class="muted">وضعیت اتصال</div><div style="margin-top:7px">{'<span class="badge premium">Calendar متصل</span>' if google_info.get("connected") else '<span class="badge free">نیاز به بررسی</span>'}<div class="muted" style="margin-top:6px">{_esc(google_info.get("error") or "مجوزهای لازم فعال است")}</div></div></div>
      </div>
    </div>
    <div class="card section subscription-card"><div class="section-head"><h2>مدیریت اشتراک</h2><span class="pill">Premium controls</span></div>
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


@router.get("/admin/auto-meetings", response_class=HTMLResponse)
async def auto_meetings_page(request: Request, q: str = "", mode: str = "enabled"):
    _require_admin(request)
    controller_state = _controller_state()
    enabled_map = controller_state.get("auto_join_all", {}) or {}
    enabled_ids = {
        str(chat_id)
        for chat_id, enabled in enabled_map.items()
        if bool(enabled)
    }
    connected_ids = _personal_token_ids()
    candidate_ids = enabled_ids | connected_ids

    with _db() as db:
        users = db.execute("SELECT * FROM users ORDER BY last_seen DESC").fetchall()
    user_map = {str(row["telegram_id"]): row for row in users}

    account_pairs = await asyncio.gather(*[
        asyncio.to_thread(_google_account_info, chat_id)
        for chat_id in sorted(candidate_ids)
    ])
    account_map = {
        chat_id: info
        for chat_id, info in zip(sorted(candidate_ids), account_pairs)
    }

    needle = q.strip().casefold()
    rows = []
    for chat_id in candidate_ids:
        user = user_map.get(chat_id)
        info = account_map.get(chat_id) or {}
        auto_enabled = chat_id in enabled_ids
        connected = bool(info.get("connected"))
        if mode == "enabled" and not auto_enabled:
            continue
        if mode == "connected" and not connected:
            continue
        if mode == "attention" and not (auto_enabled and not connected):
            continue

        name = ""
        username = ""
        last_seen = None
        if user:
            name = (f'{user["first_name"]} {user["last_name"]}').strip()
            username = str(user["username"] or "")
            last_seen = user["last_seen"]
        label = name or (f"@{username}" if username else chat_id)
        email = str(info.get("email") or "")

        haystack = " ".join([chat_id, name, username, email]).casefold()
        if needle and needle not in haystack:
            continue

        rows.append({
            "telegram_id": chat_id,
            "name": label,
            "username": username,
            "auto_enabled": auto_enabled,
            "connected": connected,
            "email": email,
            "error": str(info.get("error") or ""),
            "token_updated_at": info.get("token_updated_at"),
            "last_seen": last_seen,
        })

    rows.sort(key=lambda item: (
        not item["auto_enabled"],
        not item["connected"],
        str(item["name"]).casefold(),
    ))

    trs = "".join(
        f"""<tr>
          <td><div class="user"><div class="avatar">{_esc((row["name"][:1] or "U").upper())}</div><div><b>{_esc(row["name"])}</b><div class="muted">{_esc("@"+row["username"] if row["username"] else row["telegram_id"])}</div></div></div></td>
          <td>{'<span class="badge premium">روشن</span>' if row["auto_enabled"] else '<span class="badge free">خاموش</span>'}</td>
          <td style="direction:ltr;text-align:right"><b>{_esc(row["email"] or "—")}</b></td>
          <td>{'<span class="badge premium">متصل</span>' if row["connected"] else '<span class="badge free">نیاز به بررسی</span>'}<div class="muted" style="margin-top:5px">{_esc(row["error"])}</div></td>
          <td class="muted">{_fa_date(row["token_updated_at"])}</td>
          <td class="muted">{_fa_date(row["last_seen"])}</td>
          <td><a class="btn" href="/admin/users/{_esc(row["telegram_id"])}">باز کردن</a></td>
        </tr>"""
        for row in rows
    ) or '<tr><td colspan="7" class="empty">کاربری با این وضعیت پیدا نشد</td></tr>'

    enabled_count = len(enabled_ids)
    connected_count = len(connected_ids)
    attention_count = sum(
        1 for chat_id in enabled_ids
        if not bool((account_map.get(chat_id) or {}).get("connected"))
    )

    mode_options = "".join(
        f'<option value="{value}" {"selected" if mode == value else ""}>{label}</option>'
        for value, label in (
            ("enabled", "فقط همه جلسات روشن"),
            ("connected", "Calendar متصل"),
            ("attention", "روشن ولی اتصال مشکل دارد"),
            ("all", "همه اتصال ها"),
        )
    )
    body = f"""
    <div class="top"><div><h1>همه جلسات و Google Calendar</h1><div class="sub">مشخص است چه کسی Auto Join را روشن کرده و کدام حساب Google به آن متصل است.</div></div>
      <form class="inline"><input class="search" name="q" value="{_esc(q)}" placeholder="نام، یوزرنیم، Telegram ID یا ایمیل"><select name="mode">{mode_options}</select><button class="btn primary">فیلتر</button></form>
    </div>
    <div class="grid">
      <div class="card metric"><div class="label">همه جلسات روشن</div><div class="num cyan">{enabled_count}</div><div class="hint">Auto Join فعال</div></div>
      <div class="card metric"><div class="label">Google Calendar متصل</div><div class="num good">{connected_count}</div><div class="hint">توکن شخصی موجود</div></div>
      <div class="card metric"><div class="label">نیاز به بررسی</div><div class="num {'warn' if attention_count else 'good'}">{attention_count}</div><div class="hint">Auto Join روشن ولی اتصال سالم نیست</div></div>
      <div class="card metric"><div class="label">نمایش فعلی</div><div class="num">{len(rows)}</div><div class="hint">ردیف بعد از فیلتر</div></div>
    </div>
    <div class="card section">
      <div class="section-head"><h2>اتصال کاربران</h2><span class="pill">ایمیل کامل فقط برای مدیر نمایش داده می شود</span></div>
      <table><thead><tr><th>کاربر</th><th>همه جلسات</th><th>Google Account</th><th>Calendar</th><th>آخرین بروزرسانی اتصال</th><th>آخرین فعالیت</th><th>جزئیات</th></tr></thead><tbody>{trs}</tbody></table>
    </div>"""
    return _layout("همه جلسات", body, "auto")


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



@router.get("/admin/system", response_class=HTMLResponse)
async def system_page(request: Request):
    _require_admin(request)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:8000/health")
            response.raise_for_status()
            health = response.json()
    except Exception as exc:
        health = {"ok": False, "error": str(exc)}

    ok = bool(health.get("ok"))
    free_slots = int(health.get("free_meeting_slots") or 0)
    premium_slots = int(health.get("premium_reserved_slots") or 0)
    free_workers = int(health.get("free_worker_endpoints") or 0)
    premium_workers = int(health.get("premium_worker_endpoints") or 0)
    healthy_free = int(health.get("healthy_free_workers") or 0)
    healthy_premium = int(health.get("healthy_premium_workers") or 0)
    free_queue = int(health.get("free_queue") or 0)
    premium_queue = int(health.get("premium_queue") or 0)
    remote_workers = int(health.get("remote_workers") or 0)
    remote_free_slots = int(health.get("remote_free_slots") or 0)
    remote_premium_slots = int(health.get("remote_premium_slots") or 0)
    db_backend = _esc(health.get("database_backend") or "نامشخص")
    redis_ok = bool(health.get("redis_state"))
    autoscaler_ok = bool(health.get("autoscaler_enabled"))

    body = f"""
    <div class="top">
      <div><h1>وضعیت سیستم</h1><div class="sub">ظرفیت، صف و زیرساخت BeOnMeet</div></div>
      <span class="pill">{'● همه چیز آنلاین' if ok and redis_ok else '● نیاز به بررسی'}</span>
    </div>

    <div class="grid">
      <div class="card metric"><div class="label">ظرفیت همزمان</div><div class="num cyan">{free_slots + premium_slots}</div><div class="hint">{free_slots} عمومی + {premium_slots} ویژه</div></div>
      <div class="card metric"><div class="label">ورکرهای عمومی</div><div class="num {'good' if healthy_free == free_workers else 'warn'}">{healthy_free}/{free_workers}</div><div class="hint">Recorder endpoint سالم</div></div>
      <div class="card metric"><div class="label">ورکرهای ویژه</div><div class="num {'good' if healthy_premium == premium_workers else 'warn'}">{healthy_premium}/{premium_workers}</div><div class="hint">ظرفیت رزرو Premium</div></div>
      <div class="card metric"><div class="label">صف فعلی</div><div class="num">{free_queue + premium_queue}</div><div class="hint">{free_queue} رایگان · {premium_queue} ویژه</div></div>
    </div>

    <div class="two section">
      <div class="card">
        <div class="section-head"><h2>زیرساخت داده</h2><span class="pill">Production</span></div>
        <div class="feature"><span class="dot"></span><div><b>Database</b><div class="muted">{db_backend}</div></div></div>
        <div class="feature"><span class="dot {'planned' if not redis_ok else ''}"></span><div><b>Redis Queue</b><div class="muted">{'متصل و پایدار' if redis_ok else 'قطع یا در دسترس نیست'}</div></div></div>
        <div class="feature"><span class="dot"></span><div><b>Calendar</b><div class="muted">{'متصل' if health.get('calendar_connected') else 'قطع'}</div></div></div>
      </div>
      <div class="card">
        <div class="section-head"><h2>معماری فعلی</h2><span class="pill">Scale ready</span></div>
        <div class="feature"><span class="dot"></span><div><b>Controller</b><div class="muted">Telegram، Calendar، Queue، پرداخت و مدیریت</div></div></div>
        <div class="feature"><span class="dot"></span><div><b>Free Pool</b><div class="muted">{free_workers} ورکر مستقل با {free_slots} اسلات</div></div></div>
        <div class="feature"><span class="dot"></span><div><b>Premium Pool</b><div class="muted">{premium_workers} ورکر محلی با {premium_slots} اسلات رزرو</div></div></div>
        <div class="feature"><span class="dot"></span><div><b>Remote Workers</b><div class="muted">{remote_workers} آنلاین · {remote_free_slots} عمومی · {remote_premium_slots} ویژه</div></div></div>
        <div class="feature"><span class="dot {'planned' if not autoscaler_ok else ''}"></span><div><b>Hetzner Autoscaler</b><div class="muted">{'فعاله و بر اساس صف ورکر می‌سازه' if autoscaler_ok else 'غیرفعاله'}</div></div></div>
        <div class="feature"><span class="dot"></span><div><b>Transcription</b><div class="muted">{health.get('transcription_concurrency', 1)} پردازش همزمان برای محافظت از ضبط‌ها</div></div></div>
      </div>
    </div>
    """
    return _layout("سیستم", body, "system")
