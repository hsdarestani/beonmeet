import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote

import httpx
from dateutil.parser import isoparse
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from state_store import DurableStateStore
from db_compat import is_postgres

from admin_panel import (
    PLANS,
    activate_subscription,
    create_payment_intent,
    get_payment_intent,
    init_db,
    is_premium,
    make_admin_login_url,
    mark_payment_paid,
    record_recording,
    record_request,
    router as admin_router,
    subscription_info,
    touch_user,
)

app = FastAPI(title="BeOnMeet Controller")
app.include_router(admin_router)

DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
TOKEN_FILE = DATA_DIR / "google-token.json"
STATE_STORE = DurableStateStore(STATE_FILE)

BOT_EMAIL = os.environ.get("BOT_EMAIL", "meetrecorderbot@gmail.com")
DOMAIN = os.environ.get("DOMAIN", "beonmeet.smarbiz.sbs")
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", f"https://{DOMAIN}/auth/google/callback")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMINUSER = os.environ.get("ADMINUSER", "").strip()
TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
MEETING_BOT_URL = os.environ.get("MEETING_BOT_URL", "http://meeting-bot:3000").rstrip("/")
FREE_MEETING_BOT_URL = os.environ.get("FREE_MEETING_BOT_URL", MEETING_BOT_URL).rstrip("/")
PREMIUM_MEETING_BOT_URL = os.environ.get("PREMIUM_MEETING_BOT_URL", FREE_MEETING_BOT_URL).rstrip("/")


def _worker_urls(env_name: str, fallback: str) -> list[str]:
    raw = os.environ.get(env_name, "").strip()
    values = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return values or [fallback]


FREE_WORKER_URLS = _worker_urls("FREE_WORKER_URLS", FREE_MEETING_BOT_URL)
PREMIUM_WORKER_URLS = _worker_urls("PREMIUM_WORKER_URLS", PREMIUM_MEETING_BOT_URL)
FREE_MEETING_SLOTS = int(os.environ.get("FREE_MEETING_SLOTS", "5"))
PREMIUM_MEETING_SLOTS = int(os.environ.get("PREMIUM_MEETING_SLOTS", "3"))
INTERNAL_SECRET = os.environ["INTERNAL_SECRET"]
RECORDING_ROOT = Path(os.environ.get("RECORDING_TMP_DIR", "/recordings")).resolve()
BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "BeOnMeet Recorder")
CALENDAR_POLL_SECONDS = int(os.environ.get("CALENDAR_POLL_SECONDS", "30"))
PAYMENT_STATUS_URL = os.environ.get(
    "PAYMENT_STATUS_URL",
    "https://pay.hamooncloud.ir/payments/beonmeet/status",
)
TRANSCRIPTION_SEMAPHORE = asyncio.Semaphore(
    max(1, int(os.environ.get("TRANSCRIPTION_CONCURRENCY", "1")))
)

MEET_RE = re.compile(r"(?:https?://)?(?:www\.)?meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:\?[^\s]*)?", re.I)
SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

state_lock = asyncio.Lock()
worker_health_cache: dict[str, bool] = {}
_whisper_model = None
state: dict[str, Any] = {
    "telegram_offset": 0,
    "requests": {},
    "launched_events": {},
    "join_queue": [],
    "oauth_state": None,
}


def load_state() -> None:
    global state
    loaded, source = STATE_STORE.load()
    if isinstance(loaded, dict):
        state.update(loaded)
    state.setdefault("join_queue", [])
    state.setdefault("requests", {})
    state.setdefault("launched_events", {})
    state.setdefault("telegram_offset", 0)
    state.setdefault("oauth_state", None)
    print(f"controller state loaded from {source}", flush=True)


def save_state_sync() -> None:
    STATE_STORE.save(state)


async def save_state() -> None:
    async with state_lock:
        await asyncio.to_thread(save_state_sync)


def normalize_meet_url(url: str) -> str:
    match = MEET_RE.search(url or "")
    if not match:
        return ""
    raw = match.group(0).split("?")[0].lower()
    raw = re.sub(r"^https?://", "", raw)
    if raw.startswith("www."):
        raw = raw[4:]
    return f"https://{raw}"


async def telegram(method: str, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/{method}"
    timeout = httpx.Timeout(1800.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data=data, files=files)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(payload)
        return payload


def telegram_reply_keyboard(chat_id: int | str) -> dict[str, Any]:
    rows = [
        [{"text": "🎬 ضبط جلسه جدید"}, {"text": "✨ پلن ویژه"}],
        [{"text": "⚡ ورود فوری"}, {"text": "❓ راهنما"}],
    ]
    if ADMINUSER and str(chat_id) == ADMINUSER:
        rows.append([{"text": "⚙️ پنل مدیریت"}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "لینک Google Meet رو بفرست…",
    }


async def tg_text(chat_id: int | str, text: str, with_menu: bool = False) -> None:
    data: dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }
    if with_menu:
        data["reply_markup"] = json.dumps(telegram_reply_keyboard(chat_id), ensure_ascii=False)
    await telegram("sendMessage", data)


async def setup_telegram_profile() -> None:
    try:
        await telegram("setMyDescription", {
            "description": "لینک Google Meet رو بفرست. سر وقت وارد جلسه می‌شم، ضبطش می‌کنم و آخرش فایل رو همینجا برات می‌فرستم."
        })
        await telegram("setMyShortDescription", {
            "short_description": "ضبط خودکار Google Meet و ارسال مستقیم توی تلگرام"
        })
        public_commands = [
            {"command": "start", "description": "راهنمای استفاده"},
            {"command": "plans", "description": "پلن ویژه و خرید اشتراک"},
            {"command": "now", "description": "ورود فوری به جلسه"},
        ]

        # Show Telegram's native command menu next to the chat input.
        await telegram("setMyCommands", {
            "scope": json.dumps({"type": "all_private_chats"}),
            "commands": json.dumps(public_commands, ensure_ascii=False),
        })
        await telegram("setChatMenuButton", {
            "menu_button": json.dumps({"type": "commands"})
        })

        if ADMINUSER:
            admin_commands = public_commands + [
                {"command": "admin", "description": "پنل مدیریت"}
            ]
            await telegram("setMyCommands", {
                "scope": json.dumps({"type": "chat", "chat_id": int(ADMINUSER)}),
                "commands": json.dumps(admin_commands, ensure_ascii=False),
            })
            await telegram("setChatMenuButton", {
                "chat_id": int(ADMINUSER),
                "menu_button": json.dumps({"type": "commands"}),
            })
    except Exception as exc:
        print("telegram profile setup error:", repr(exc), flush=True)


def google_flow(state_value: str | None = None) -> Flow:
    cfg = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(cfg, scopes=SCOPES, state=state_value)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def load_google_credentials() -> Credentials | None:
    if not TOKEN_FILE.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def list_calendar_events() -> list[dict[str, Any]]:
    creds = load_google_credentials()
    if not creds:
        return []
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.now(timezone.utc)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=(now - timedelta(minutes=30)).isoformat(),
            timeMax=(now + timedelta(days=14)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    calendar_tz = None
    try:
        calendar_tz = (
            service.calendars()
            .get(calendarId="primary")
            .execute()
            .get("timeZone")
        )
    except Exception:
        pass
    if not calendar_tz:
        try:
            calendar_tz = service.settings().get(setting="timezone").execute().get("value")
        except Exception:
            pass
    events = result.get("items", [])
    if calendar_tz:
        for event in events:
            event["_calendarTimeZone"] = calendar_tz
    return events


def event_meet_url(event: dict[str, Any]) -> str:
    if event.get("hangoutLink"):
        return normalize_meet_url(event["hangoutLink"])
    for ep in event.get("conferenceData", {}).get("entryPoints", []):
        uri = ep.get("uri", "")
        if "meet.google.com" in uri:
            return normalize_meet_url(uri)
    for field in ("location", "description"):
        found = normalize_meet_url(event.get(field, ""))
        if found:
            return found
    return ""


def _event_timezone_name(event: dict[str, Any], edge: str = "start") -> str | None:
    return (
        event.get(edge, {}).get("timeZone")
        or event.get("start", {}).get("timeZone")
        or event.get("_calendarTimeZone")
    )


def _event_datetime(event: dict[str, Any], edge: str) -> datetime | None:
    value = event.get(edge, {}).get("dateTime")
    if not value:
        return None
    dt = isoparse(value)
    tz_name = _event_timezone_name(event, edge)
    tz = None
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz or timezone.utc)
    if tz:
        return dt.astimezone(tz)
    return dt


def event_start(event: dict[str, Any]) -> datetime | None:
    return _event_datetime(event, "start")


def event_end(event: dict[str, Any]) -> datetime | None:
    return _event_datetime(event, "end")


def find_calendar_event_for_meet(meet_url: str) -> dict[str, Any] | None:
    matches = [event for event in list_calendar_events() if event_meet_url(event) == meet_url]
    if not matches:
        return None

    now = datetime.now(timezone.utc)

    def event_rank(event: dict[str, Any]) -> tuple[int, float]:
        start = event_start(event)
        end = event_end(event)
        if not start:
            return (3, float("inf"))

        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc) if end else start_utc + timedelta(hours=3)

        # Prefer the occurrence that is live right now, then the next upcoming one,
        # then the most recently finished occurrence. This avoids matching an older
        # recurring/reused Meet link.
        if start_utc <= now <= end_utc + timedelta(minutes=10):
            return (0, abs((now - start_utc).total_seconds()))
        if start_utc > now:
            return (1, (start_utc - now).total_seconds())
        return (2, (now - end_utc).total_seconds())

    return min(matches, key=event_rank)


def fmt_event_time(event: dict[str, Any]) -> str:
    start = event_start(event)
    end = event_end(event)
    if not start:
        return "زمان نامشخص"
    tz_name = _event_timezone_name(event, "start")
    tz_label = f" ({tz_name})" if tz_name else ""
    if end:
        return f"{start.strftime('%Y-%m-%d %H:%M')} تا {end.strftime('%H:%M')}{tz_label}"
    return f"{start.strftime('%Y-%m-%d %H:%M')}{tz_label}"


def _queue_event_id(event: dict[str, Any]) -> str:
    return str(event.get("id") or "")


def _is_queued(event_id: str) -> bool:
    return any(str(item.get("event_id") or "") == str(event_id) for item in state.get("join_queue", []))


def _queue_position(event_id: str, premium: bool) -> int:
    queue = state.get("join_queue", [])
    ordered = sorted(
        queue,
        key=lambda item: (
            0 if bool(item.get("premium")) else 1,
            str(item.get("queued_at") or ""),
        ),
    )
    matching = [
        item for item in ordered
        if bool(item.get("premium")) == bool(premium)
    ]
    for idx, item in enumerate(matching, 1):
        if str(item.get("event_id") or "") == str(event_id):
            return idx
    return len(matching) + 1


async def enqueue_meeting(
    event: dict[str, Any],
    req: dict[str, Any],
    meet_url: str,
    premium: bool,
    notify: bool = True,
) -> None:
    event_id = _queue_event_id(event) or f"queued-{uuid.uuid4()}"
    if _is_queued(event_id):
        return

    state.setdefault("join_queue", []).append({
        "event_id": event_id,
        "event": event,
        "req": req,
        "meet_url": meet_url,
        "premium": bool(premium),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    })
    await save_state()

    if not notify:
        return

    chat_id = str(req["chat_id"])
    position = _queue_position(event_id, premium)
    if premium:
        await tg_text(
            chat_id,
            "⚡ ظرفیت اختصاصی پلن ویژه و ظرفیت اضافه فعلاً همزمان پر شدن. "
            f"درخواستت با اولویت ویژه ثبت شد و نفر {position} صف ویژه‌ای. "
            "به محض آزاد شدن اولین ورکر، مستقیم وارد می‌شم."
        )
    else:
        await tg_text(
            chat_id,
            f"⏳ رکوردرهای رایگان الان پرن. درخواستت تو صف ثبت شد و نفر {position} صفی. "
            "به محض آزاد شدن ظرفیت، خودکار وارد جلسه می‌شم."
        )


async def _dispatch_meeting(
    event: dict[str, Any],
    req: dict[str, Any],
    meet_url: str,
    premium: bool,
) -> tuple[bool, bool, str]:
    event_id = event.get("id") or str(uuid.uuid4())
    chat_id = str(req["chat_id"])
    payload = {
        "bearerToken": "beonmeet-local",
        "url": meet_url,
        "name": BOT_DISPLAY_NAME,
        "teamId": "beonmeet-premium" if premium else "beonmeet-free",
        "timezone": "UTC",
        "userId": chat_id,
        "eventId": event_id,
        "botId": event_id,
    }

    # Premium always gets the reserved worker pool first. If it is full, Premium
    # is allowed to borrow unused capacity from the free pool. Free users can
    # never consume the reserved Premium pool.
    targets: list[tuple[str, str]] = []
    if premium:
        for idx, url in enumerate(PREMIUM_WORKER_URLS, 1):
            targets.append((f"premium-{idx}", url))
        for idx, url in enumerate(FREE_WORKER_URLS, 1):
            if url not in PREMIUM_WORKER_URLS:
                targets.append((f"free-overflow-{idx}", url))
    else:
        for idx, url in enumerate(FREE_WORKER_URLS, 1):
            targets.append((f"free-{idx}", url))

    saw_busy = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        for pool_name, base_url in targets:
            try:
                response = await client.post(f"{base_url}/google/join", json=payload)
            except Exception as exc:
                print(f"meeting dispatch error ({pool_name}):", repr(exc), flush=True)
                continue

            if response.status_code == 202:
                state["launched_events"][event_id] = {
                    "meet_url": meet_url,
                    "chat_id": chat_id,
                    "launched_at": datetime.now(timezone.utc).isoformat(),
                    "status": "joining",
                    "premium": bool(premium),
                    "pool": pool_name,
                }
                await save_state()
                return True, False, pool_name

            if response.status_code == 409:
                saw_busy = True
                continue

            print(
                "meeting dispatch rejected:",
                pool_name,
                response.status_code,
                response.text[:500],
                flush=True,
            )

    return False, saw_busy, ""


async def launch_meeting(
    event: dict[str, Any],
    req: dict[str, Any],
    meet_url: str,
    *,
    queue_if_busy: bool = True,
    notify_start: bool = True,
) -> bool:
    chat_id = str(req["chat_id"])
    premium = await asyncio.to_thread(is_premium, chat_id)

    launched, busy, pool_name = await _dispatch_meeting(
        event, req, meet_url, premium
    )
    if launched:
        if notify_start:
            if premium and pool_name.startswith("premium-"):
                await tg_text(
                    chat_id,
                    f"⚡ ورکر اختصاصی پلن ویژه رزرو شد. دارم وارد جلسه می‌شم…\n{meet_url}"
                )
            elif premium:
                await tg_text(
                    chat_id,
                    f"⚡ با اولویت ویژه از ظرفیت آزاد وارد صف اجرا شدم. دارم وارد جلسه می‌شم…\n{meet_url}"
                )
            else:
                await tg_text(
                    chat_id,
                    f"⏳ درخواست ورود به جلسه ارسال شد. دارم وارد می‌شم…\n{meet_url}"
                )
        return True

    if busy and queue_if_busy:
        await enqueue_meeting(event, req, meet_url, premium, notify=True)
        return False

    if not busy and notify_start:
        await tg_text(
            chat_id,
            f"⚠️ فعلاً نتونستم درخواست ورود رو به رکوردر برسونم. خودم دوباره امتحان می‌کنم.\n{meet_url}"
        )
    return False


async def worker_health_loop() -> None:
    global worker_health_cache
    while True:
        urls = list(dict.fromkeys(FREE_WORKER_URLS + PREMIUM_WORKER_URLS))
        results: dict[str, bool] = {}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                async def check(url: str) -> tuple[str, bool]:
                    try:
                        response = await client.get(f"{url}/health")
                        return url, response.status_code == 200
                    except Exception:
                        return url, False

                checks = await asyncio.gather(*(check(url) for url in urls))
                results = dict(checks)
        except Exception as exc:
            print("worker health loop error:", repr(exc), flush=True)

        if results:
            worker_health_cache = results
        await asyncio.sleep(10)


async def queue_loop() -> None:
    while True:
        try:
            queue = state.setdefault("join_queue", [])
            if queue:
                ordered = sorted(
                    list(queue),
                    key=lambda item: (
                        0 if bool(item.get("premium")) else 1,
                        str(item.get("queued_at") or ""),
                    ),
                )
                for item in ordered:
                    event_id = str(item.get("event_id") or "")
                    event = item.get("event") or {}
                    req = item.get("req") or {}
                    meet_url = str(item.get("meet_url") or "")
                    premium = bool(item.get("premium"))
                    chat_id = str(req.get("chat_id") or "")

                    if not event_id or not chat_id or not meet_url:
                        state["join_queue"] = [
                            q for q in state.get("join_queue", [])
                            if str(q.get("event_id") or "") != event_id
                        ]
                        await save_state()
                        continue

                    end = event_end(event)
                    if end and datetime.now(timezone.utc) > end.astimezone(timezone.utc) + timedelta(minutes=5):
                        state["join_queue"] = [
                            q for q in state.get("join_queue", [])
                            if str(q.get("event_id") or "") != event_id
                        ]
                        await save_state()
                        await tg_text(
                            chat_id,
                            "⌛ نوبت رکوردر قبل از پایان جلسه آزاد نشد و این درخواست از صف خارج شد."
                        )
                        continue

                    launched, busy, pool_name = await _dispatch_meeting(
                        event, req, meet_url, premium
                    )
                    if launched:
                        state["join_queue"] = [
                            q for q in state.get("join_queue", [])
                            if str(q.get("event_id") or "") != event_id
                        ]
                        await save_state()
                        if premium:
                            await tg_text(
                                chat_id,
                                f"⚡ ظرفیت ویژه آزاد شد و الان دارم وارد جلسه می‌شم…\n{meet_url}"
                            )
                        else:
                            await tg_text(
                                chat_id,
                                f"✅ نوبتت از صف رسید. الان دارم وارد جلسه می‌شم…\n{meet_url}"
                            )
                    elif not busy:
                        # Transient dispatch/network error. Keep the queue item and retry.
                        continue
        except Exception as exc:
            print("queue loop error:", repr(exc), flush=True)
        await asyncio.sleep(3)


async def calendar_loop() -> None:
    while True:
        try:
            if TOKEN_FILE.exists():
                events = await asyncio.to_thread(list_calendar_events)
                now = datetime.now(timezone.utc)
                for event in events:
                    meet_url = event_meet_url(event)
                    if not meet_url:
                        continue
                    req = state["requests"].get(meet_url)
                    if not req:
                        continue
                    event_id = event.get("id")
                    if not event_id:
                        continue
                    if _is_queued(str(event_id)):
                        continue
                    launched = state["launched_events"].get(event_id)
                    if launched:
                        status = str(launched.get("status") or "joining")
                        launched_at_raw = launched.get("launched_at")
                        launched_at = isoparse(launched_at_raw) if launched_at_raw else None
                        if status in {"recording", "waiting_for_admission"}:
                            continue
                        if launched_at and now - launched_at < timedelta(minutes=7):
                            continue
                        state["launched_events"].pop(event_id, None)
                        await save_state()
                    start = event_start(event)
                    end = event_end(event)
                    if not start:
                        continue
                    if end and now > end:
                        continue
                    live_until = (end + timedelta(minutes=5)) if end else (start + timedelta(hours=3))
                    if start <= now <= live_until:
                        await launch_meeting(event, req, meet_url)
        except Exception as exc:
            print("calendar loop error:", repr(exc), flush=True)
        await asyncio.sleep(CALENDAR_POLL_SECONDS)


async def telegram_loop() -> None:
    while True:
        try:
            offset = int(state.get("telegram_offset") or 0)
            url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=20.0)) as client:
                r = await client.post(url, data={"timeout": 30, "offset": offset, "allowed_updates": json.dumps(["message"])})
                r.raise_for_status()
                updates = r.json().get("result", [])
            for upd in updates:
                state["telegram_offset"] = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                from_user = msg.get("from") or {}
                chat_id = chat.get("id")
                text = msg.get("text") or msg.get("caption") or ""
                if not chat_id:
                    continue

                await asyncio.to_thread(
                    touch_user,
                    str(chat_id),
                    str(from_user.get("username") or chat.get("username") or ""),
                    str(from_user.get("first_name") or chat.get("first_name") or ""),
                    str(from_user.get("last_name") or chat.get("last_name") or ""),
                )

                if text == "⚙️ پنل مدیریت":
                    text = "/admin"
                elif text == "✨ پلن ویژه":
                    text = "/plans"
                elif text == "⚡ ورود فوری":
                    text = "/now"
                elif text == "❓ راهنما":
                    text = "/start"
                elif text == "🎬 ضبط جلسه جدید":
                    await tg_text(
                        chat_id,
                        "لینک Google Meet رو همینجا بفرست. اگه جلسه توی کلندر باشه سر وقت وارد می‌شم؛ اگه همین الان شروع شده می‌تونی از «⚡ ورود فوری» استفاده کنی.",
                        with_menu=True,
                    )
                    continue

                if text.startswith("/admin"):
                    if ADMINUSER and str(chat_id) == ADMINUSER:
                        await tg_text(chat_id, f"پنل مدیریت آماده‌ست 👇\n{make_admin_login_url()}\n\nاین لینک ۱۵ دقیقه اعتبار داره.")
                    else:
                        await tg_text(chat_id, "این بخش فقط برای مدیر رباته 🙂")
                    continue

                if text.startswith("/plans") or text.startswith("/premium"):
                    info = await asyncio.to_thread(subscription_info, str(chat_id))
                    if info.get("premium"):
                        until = info.get("until")
                        until_text = until.astimezone().strftime("%Y/%m/%d") if until else ""
                        await tg_text(
                            chat_id,
                            f"✨ پلن ویژه‌ت فعاله تا {until_text}.\n\n"
                            "قابلیت‌های ویژه:\n"
                            "• کیفیت بالاتر ضبط\n"
                            "• فایل صوتی جداگانه\n"
                            "• متن جلسه\n"
                            "• پیش نویس صورتجلسه\n"
                            "• ظرفیت اختصاصی و اولویت ورود؛ پشت صف کاربران رایگان نمی‌مونی",
                            with_menu=True,
                        )
                    else:
                        intents = {}
                        for plan_code in ("monthly", "quarterly", "halfyear"):
                            intents[plan_code] = await asyncio.to_thread(
                                create_payment_intent, str(chat_id), plan_code
                            )
                        keyboard = {
                            "inline_keyboard": [
                                [{
                                    "text": "۱ ماهه · ۱۹۸ هزار تومان",
                                    "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['monthly']['intent']}",
                                }],
                                [{
                                    "text": "۳ ماهه · ۴۹۹ هزار تومان",
                                    "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['quarterly']['intent']}",
                                }],
                                [{
                                    "text": "۶ ماهه · ۷۹۹ هزار تومان",
                                    "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['halfyear']['intent']}",
                                }],
                            ]
                        }
                        await telegram(
                            "sendMessage",
                            {
                                "chat_id": str(chat_id),
                                "text": (
                                    "✨ پلن ویژه BeOnMeet\n\n"
                                    "قابلیت‌ها:\n"
                                    "• کیفیت بالاتر ضبط\n"
                                    "• فایل صوتی جداگانه\n"
                                    "• متن جلسه\n"
                                    "• پیش نویس صورتجلسه\n"
                                    "• ظرفیت اختصاصی و اولویت ورود؛ پشت صف کاربران رایگان نمی‌مونی\n\n"
                                    "یکی از پلن‌ها رو انتخاب کن:"
                                ),
                                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                            },
                        )
                    continue

                if text.startswith("/start"):
                    auth_status = "✅ کلندر وصله" if TOKEN_FILE.exists() else f"⚠️ کلندر هنوز وصل نیست\nhttps://{DOMAIN}/auth/google"
                    await tg_text(
                        chat_id,
                        "سلام 👋 من BeOnMeet هستم.\n\n"
                        "لینک Google Meet رو برام بفرست. "
                        f"فقط یادت باشه {BOT_EMAIL} رو هم به همون ایونت کلندر دعوت کنی. "
                        "سر وقت خودم وارد میت می‌شم، ضبطش می‌کنم و آخرش فایل رو همینجا برات می‌فرستم.\n\n"
                        + auth_status,
                        with_menu=True,
                    )
                    continue
                if text.strip().lower() == "/now":
                    state.setdefault("pending_now", {})[str(chat_id)] = True
                    await save_state()
                    await tg_text(chat_id, "باشه. حالا لینک Google Meet رو بفرست تا همین الان واردش بشم.", with_menu=True)
                    continue

                force_now = text.strip().lower().startswith("/now") or bool(
                    state.setdefault("pending_now", {}).pop(str(chat_id), False)
                )
                meet_url = normalize_meet_url(text)
                if meet_url:
                    state["requests"][meet_url] = {
                        "chat_id": str(chat_id),
                        "requester_id": str(from_user.get("id") or chat_id),
                        "first_name": from_user.get("first_name") or chat.get("first_name") or "",
                        "last_name": from_user.get("last_name") or chat.get("last_name") or "",
                        "username": from_user.get("username") or chat.get("username") or "",
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await save_state()
                    await asyncio.to_thread(record_request, str(chat_id), meet_url, "now" if force_now else "calendar")

                    if force_now:
                        synthetic_event = {
                            "id": f"manual-{uuid.uuid4()}",
                            "start": {"dateTime": datetime.now(timezone.utc).isoformat()},
                            "end": {"dateTime": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()},
                        }
                        await launch_meeting(synthetic_event, state["requests"][meet_url], meet_url)
                        continue

                    try:
                        matched_event = await asyncio.to_thread(find_calendar_event_for_meet, meet_url)
                    except Exception as exc:
                        print("calendar lookup error after Telegram request:", repr(exc), flush=True)
                        await tg_text(
                            chat_id,
                            "⚠️ درخواستت ذخیره شد ولی الان نتونستم کلندر گوگل رو بخونم. یه کوچولو بعد دوباره لینک رو بفرست.",
                        )
                        continue

                    if matched_event:
                        when = fmt_event_time(matched_event)
                        await tg_text(
                            chat_id,
                            f"✅ گرفتمش. ایونت کلندر هم پیدا شد.\n{meet_url}\n🕒 {when}",
                        )
                        now = datetime.now(timezone.utc)
                        start = event_start(matched_event)
                        end = event_end(matched_event)
                        live_until = (end + timedelta(minutes=5)) if end else ((start + timedelta(hours=3)) if start else now)
                        if start and start <= now <= live_until:
                            await launch_meeting(matched_event, state["requests"][meet_url], meet_url)
                    else:
                        await tg_text(
                            chat_id,
                            f"⚠️ لینکت رو ذخیره کردم، ولی هنوز این جلسه رو توی کلندر {BOT_EMAIL} نمی‌بینم.\n\n"
                            f"اول {BOT_EMAIL} رو به ایونت دعوت کن. اگه قبلاً دعوتش کردی، توی تنظیمات Google Calendar همین اکانت گزینه «Add invitations to my calendar» رو روی «From everyone» بذار یا دعوت فعلی رو قبول کن. بعد لینک رو دوباره برام بفرست.\n\n"
                            "اگه جلسه همین الان شروع شده و می‌خوای بدون منتظر موندن وارد بشم، اینو بفرست:\n"
                            f"/now {meet_url}",
                        )
                else:
                    await tg_text(chat_id, "یه لینک Google Meet برام بفرست، مثلاً:\nhttps://meet.google.com/abc-defg-hij")
        except Exception as exc:
            print("telegram loop error:", repr(exc), flush=True)
            await asyncio.sleep(5)


async def send_recording_to_recipients(
    recipients: list[dict[str, str]],
    path: Path,
    filename: str,
) -> None:
    max_cloud = 49 * 1024 * 1024
    size = path.stat().st_size

    async def send_one_file(target: dict[str, str], file_path: Path, send_name: str, caption: str, mime: str) -> None:
        with file_path.open("rb") as fp:
            await telegram(
                "sendDocument",
                {"chat_id": target["chat_id"], "caption": caption},
                {"document": (send_name, fp, mime)},
            )

    if size <= max_cloud or TELEGRAM_API_BASE != "https://api.telegram.org":
        mime = "video/webm" if filename.endswith(".webm") else "video/mp4"
        for target in recipients:
            await send_one_file(target, path, filename, target["caption"], mime)
        return

    # Cloud Bot API has a small upload limit. Create playable compressed parts in RAM once,
    # then deliver every part to the requester and the admin.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    duration = max(float(probe.stdout.strip() or "0"), 1.0)
    target_seconds = max(90, min(300, int(duration * (42 * 1024 * 1024) / size)))
    part_pattern = str(path.parent / f"{path.stem}_part_%03d.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(path),
            "-vf", "scale=min(1280\\,iw):-2",
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "650k",
            "-c:a", "aac", "-b:a", "64k",
            "-f", "segment", "-segment_time", str(target_seconds),
            "-reset_timestamps", "1", part_pattern,
        ],
        check=True,
    )
    parts = sorted(path.parent.glob(f"{path.stem}_part_*.mp4"))
    for target in recipients:
        await tg_text(target["chat_id"], f"حجم ویدیو زیاده، برای همین توی {len(parts)} قسمت قابل پخش می‌فرستم.")
        for idx, part in enumerate(parts, 1):
            caption = f"{target['caption']}\n\nقسمت {idx} از {len(parts)}"
            await send_one_file(target, part, part.name, caption, "video/mp4")
    for part in parts:
        part.unlink(missing_ok=True)


def transcribe_audio_local(audio_path: Path) -> tuple[str, str]:
    global _whisper_model
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        # Medium is much more reliable for Persian and multilingual meetings than
        # the previous base model. With 16 vCPU / 32 GB RAM and transcription
        # concurrency=1 it is a safe quality/performance tradeoff.
        model_name = os.environ.get("WHISPER_MODEL", "medium")
        _whisper_model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=max(4, min(12, (os.cpu_count() or 8) - 2)),
            download_root=str(DATA_DIR / "whisper-models"),
        )

    segments, info = _whisper_model.transcribe(
        str(audio_path),
        beam_size=5,
        best_of=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
        condition_on_previous_text=True,
        multilingual=True,
        language_detection_threshold=0.70,
        language_detection_segments=5,
    )

    lines = []
    for segment in segments:
        text_value = (segment.text or "").strip()
        if not text_value:
            continue
        minutes = int(segment.start // 60)
        seconds = int(segment.start % 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {text_value}")

    language = getattr(info, "language", None) or "unknown"
    probability = float(getattr(info, "language_probability", 0.0) or 0.0)
    language_label = f"{language} ({probability * 100:.0f}٪) · تشخیص چندزبانه فعاله"
    return "\n".join(lines).strip(), language_label


def requester_summary(req: dict[str, Any], fallback_chat_id: str) -> str:
    full_name = " ".join(
        p for p in [str(req.get("first_name") or "").strip(), str(req.get("last_name") or "").strip()] if p
    ).strip()
    username = str(req.get("username") or "").strip()
    requester_id = str(req.get("requester_id") or fallback_chat_id)
    bits = []
    if full_name:
        bits.append(full_name)
    if username:
        bits.append(f"@{username}")
    if not bits:
        bits.append("کاربر تلگرام")
    return f"{' '.join(bits)}\n🆔 {requester_id}"

@app.on_event("startup")
async def startup() -> None:
    init_db()
    load_state()
    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(setup_telegram_profile())
    asyncio.create_task(telegram_loop())
    asyncio.create_task(calendar_loop())
    asyncio.create_task(queue_loop())
    asyncio.create_task(worker_health_loop())


@app.get("/api/billing/payment-intent")
async def billing_payment_intent(intent: str) -> dict[str, Any]:
    row = await asyncio.to_thread(get_payment_intent, intent)
    if not row:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    plan = PLANS.get(str(row.get("plan_code") or ""))
    if not plan:
        raise HTTPException(status_code=409, detail="Unknown plan")
    return {
        "ok": True,
        "intent": intent,
        "status": row.get("status"),
        "plan": row.get("plan_code"),
        "amount_toman": int(row.get("amount_toman") or 0),
        "label": f"پلن ویژه BeOnMeet، {plan['label']}",
    }


@app.get("/api/billing/payment-return", response_class=HTMLResponse)
async def billing_payment_return(payment: str = "", receipt: str = "", intent: str = "") -> str:
    row = await asyncio.to_thread(get_payment_intent, intent)
    if not row:
        return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;padding:40px'>پرداخت پیدا نشد.</body></html>"

    if payment != "success" or not receipt:
        return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;padding:40px'>پرداخت انجام نشد یا لغو شد. می‌تونی برگردی تلگرام و دوباره امتحان کنی.</body></html>"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(PAYMENT_STATUS_URL, params={"receipt": receipt})
        response.raise_for_status()
        status = response.json()
    except Exception:
        return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;padding:40px'>پرداخت انجام شده ولی تأیید نهایی فعلاً در دسترس نیست. چند دقیقه دیگه دوباره وضعیت پلن رو چک کن.</body></html>"

    expected_plan = str(row.get("plan_code") or "")
    expected_amount = int(row.get("amount_toman") or 0)
    if (
        not status.get("ok")
        or status.get("status") != "paid"
        or status.get("intent") != intent
        or status.get("plan") != expected_plan
        or int(status.get("amount_toman") or 0) != expected_amount
    ):
        return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;padding:40px'>تأیید پرداخت کامل نشد. اگه مبلغ کم شده، رسید محفوظ می‌مونه و می‌تونیم پیگیریش کنیم.</body></html>"

    already_paid = row.get("status") == "paid"
    paid_row = await asyncio.to_thread(mark_payment_paid, intent, receipt)
    telegram_id = str((paid_row or row).get("telegram_id") or "")
    if not already_paid:
        until = await asyncio.to_thread(activate_subscription, telegram_id, expected_plan, f"Zibal receipt {receipt}")
        await tg_text(
            telegram_id,
            f"✨ پرداختت تأیید شد و پلن ویژه فعال شد.\nتا {until.astimezone().strftime('%Y/%m/%d')} فعاله."
        )
        if ADMINUSER and ADMINUSER != telegram_id:
            await tg_text(
                ADMINUSER,
                f"💳 خرید پلن ویژه\nکاربر: {telegram_id}\nپلن: {expected_plan}\nمبلغ: {expected_amount:,} تومان\nرسید: {receipt}"
            )

    return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;background:#0b0e17;color:white;display:grid;place-items:center;min-height:100vh;margin:0'><div style='text-align:center'><h2>پرداخت موفق بود ✅</h2><p>پلن ویژه فعال شد. می‌تونی این صفحه رو ببندی و برگردی تلگرام.</p></div></body></html>"


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "calendar_connected": TOKEN_FILE.exists(),
        "bot_email": BOT_EMAIL,
        "admin_recipient_configured": bool(ADMINUSER),
        "max_concurrent_meetings": FREE_MEETING_SLOTS + PREMIUM_MEETING_SLOTS,
        "free_meeting_slots": FREE_MEETING_SLOTS,
        "premium_reserved_slots": PREMIUM_MEETING_SLOTS,
        "free_worker_endpoints": len(FREE_WORKER_URLS),
        "premium_worker_endpoints": len(PREMIUM_WORKER_URLS),
        "redis_state": STATE_STORE.ping(),
        "database_backend": "postgresql" if is_postgres() else "sqlite",
        "healthy_free_workers": sum(1 for url in FREE_WORKER_URLS if worker_health_cache.get(url, True)),
        "healthy_premium_workers": sum(1 for url in PREMIUM_WORKER_URLS if worker_health_cache.get(url, True)),
        "free_queue": sum(1 for item in state.get("join_queue", []) if not bool(item.get("premium"))),
        "premium_queue": sum(1 for item in state.get("join_queue", []) if bool(item.get("premium"))),
        "transcription_concurrency": int(os.environ.get("TRANSCRIPTION_CONCURRENCY", "1")),
    }


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    status = "connected" if TOKEN_FILE.exists() else "not connected"
    fa_status = "وصله ✅" if TOKEN_FILE.exists() else "هنوز وصل نیست ⚠️"
    return f"<h1>BeOnMeet</h1><p>Google Calendar: {fa_status}</p><p><a href='/auth/google'>وصل کردن کلندر</a></p>"


@app.get("/auth/google")
async def auth_google() -> RedirectResponse:
    flow = google_flow()
    authorization_url, oauth_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    state["oauth_state"] = oauth_state
    await save_state()
    return RedirectResponse(authorization_url)


@app.get("/auth/google/callback", response_class=HTMLResponse)
async def auth_google_callback(request: Request, state: str) -> str:
    if state != globals()["state"].get("oauth_state"):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    flow = google_flow(state)
    callback_url = f"https://{DOMAIN}/auth/google/callback?{request.url.query}"
    flow.fetch_token(authorization_response=callback_url)
    creds = flow.credentials
    TOKEN_FILE.write_text(creds.to_json())
    globals()["state"]["oauth_state"] = None
    await save_state()
    return "<h2>کلندر با موفقیت وصل شد ✅</h2><p>می‌تونی این صفحه رو ببندی و برگردی تلگرام.</p>"


@app.post("/internal/waiting-for-admission")
async def waiting_for_admission(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    chat_id = str(data.get("userId") or "").strip()
    event_id = str(data.get("eventId") or data.get("botId") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Missing userId")

    already_notified = False
    if event_id:
        launched = state["launched_events"].setdefault(event_id, {})
        already_notified = launched.get("status") == "waiting_for_admission"
        launched["status"] = "waiting_for_admission"
        launched["waiting_since"] = datetime.now(timezone.utc).isoformat()
        await save_state()

    if not already_notified:
        await tg_text(
            chat_id,
            "🚪 رسیدم پشت در جلسه. Google Meet از میزبان می‌خواد منو Admit کنه. "
            "به محض اینکه وارد بشم، ضبط خودکار شروع می‌شه."
        )
    return {"ok": True}


@app.post("/internal/recording-started")
async def recording_started(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    chat_id = str(data.get("userId") or "").strip()
    event_id = str(data.get("eventId") or data.get("botId") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Missing userId")

    already_notified = False
    if event_id:
        launched = state["launched_events"].setdefault(event_id, {})
        already_notified = launched.get("status") == "recording"
        launched["status"] = "recording"
        launched["recording_started_at"] = datetime.now(timezone.utc).isoformat()
        await save_state()

    if not already_notified:
        await tg_text(chat_id, "🎥 وارد جلسه شدم و ضبط شروع شد.")
    return {"ok": True}


async def _process_recording(data: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    try:
        raw_path.relative_to(RECORDING_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recording path")
    if not raw_path.exists() or not raw_path.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")

    chat_id = str(data.get("userId", "")).strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Missing userId")
    filename = str(data.get("filename") or raw_path.name)
    meeting_link = normalize_meet_url(str(data.get("meetingLink") or ""))
    req = state.get("requests", {}).get(meeting_link, {}) if meeting_link else {}
    who = requester_summary(req, chat_id)

    recipients = [
        {
            "chat_id": chat_id,
            "caption": "🎥 ضبط جلسه‌ت آماده‌ست",
        }
    ]
    if ADMINUSER and ADMINUSER != chat_id:
        admin_caption = (
            "🎥 یک ضبط جدید آماده شد\n\n"
            f"👤 درخواست دهنده:\n{who}\n"
            f"🔗 جلسه: {meeting_link or str(data.get('meetingLink') or 'نامشخص')}"
        )
        recipients.append({"chat_id": ADMINUSER, "caption": admin_caption})

    try:
        premium_active = await asyncio.to_thread(is_premium, chat_id)
        delivery_path = raw_path
        delivery_filename = filename
        free_path: Path | None = None

        if not premium_active:
            free_path = raw_path.with_name(f"{raw_path.stem}_standard.mp4")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-vf", "scale='min(1280,iw)':-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1200k",
                    "-c:a", "aac", "-b:a", "96k",
                    str(free_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            delivery_path = free_path
            delivery_filename = f"{Path(filename).stem}.mp4"

        await tg_text(chat_id, "✅ جلسه تموم شد. دارم فایل ضبط شده رو برات می‌فرستم…")
        await send_recording_to_recipients(recipients, delivery_path, delivery_filename)

        await asyncio.to_thread(
            record_recording,
            chat_id,
            meeting_link,
            delivery_filename,
            int(delivery_path.stat().st_size),
            int(data.get("duration") or 0),
        )

        if premium_active:
            audio_path = raw_path.with_suffix(".mp3")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(raw_path), "-vn", "-c:a", "libmp3lame", "-b:a", "160k", str(audio_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                audio_targets = [
                    {"chat_id": chat_id, "caption": "🎧 فایل صوتی جداگانه جلسه‌ت آماده‌ست"}
                ]
                if ADMINUSER and ADMINUSER != chat_id:
                    audio_targets.append({
                        "chat_id": ADMINUSER,
                        "caption": f"🎧 فایل صوتی نسخه ویژه\n\n👤 درخواست دهنده:\n{who}\n🔗 جلسه: {meeting_link or 'نامشخص'}",
                    })
                for target in audio_targets:
                    with audio_path.open("rb") as fp:
                        await telegram(
                            "sendDocument",
                            {"chat_id": target["chat_id"], "caption": target["caption"]},
                            {"document": (f"{Path(filename).stem}.mp3", fp, "audio/mpeg")},
                        )

                try:
                    await tg_text(chat_id, "📝 دارم متن جلسه رو هم آماده می‌کنم. ممکنه یه کم طول بکشه…")
                    async with TRANSCRIPTION_SEMAPHORE:
                        transcript, detected_language = await asyncio.to_thread(transcribe_audio_local, audio_path)
                    if transcript:
                        transcript_path = raw_path.with_name(f"{raw_path.stem}_transcript.txt")
                        transcript_path.write_text(
                            "متن خودکار جلسه BeOnMeet\n"
                            "توجه: این متن به صورت خودکار ساخته شده و ممکنه خطا داشته باشه.\n"
                            f"تشخیص زبان: {detected_language}\n\n"
                            + transcript,
                            encoding="utf-8",
                        )
                        transcript_targets = [
                            {"chat_id": chat_id, "caption": "📝 متن جلسه آماده‌ست. حتماً یه مرور روش داشته باش چون ممکنه خطا داشته باشه."}
                        ]
                        if ADMINUSER and ADMINUSER != chat_id:
                            transcript_targets.append({
                                "chat_id": ADMINUSER,
                                "caption": f"📝 متن جلسه نسخه ویژه\n\n👤 درخواست دهنده:\n{who}\n🔗 جلسه: {meeting_link or 'نامشخص'}",
                            })
                        for target in transcript_targets:
                            with transcript_path.open("rb") as fp:
                                await telegram(
                                    "sendDocument",
                                    {"chat_id": target["chat_id"], "caption": target["caption"]},
                                    {"document": (f"{Path(filename).stem}-transcript.txt", fp, "text/plain")},
                                )
                        transcript_path.unlink(missing_ok=True)
                    else:
                        await tg_text(chat_id, "📝 از این جلسه متن قابل استفاده‌ای درنیومد. احتمالاً صدا خیلی کم یا نامفهوم بوده.")
                except Exception as transcript_error:
                    print("transcription error:", repr(transcript_error), flush=True)
                    await tg_text(chat_id, "⚠️ فایل صوتی آماده شد ولی تبدیلش به متن این بار خطا خورد. ویدیو و صوتت سر جاشه.")
            finally:
                audio_path.unlink(missing_ok=True)

        if free_path:
            free_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)
        return {"ok": True, "admin_copy": bool(ADMINUSER), "premium": premium_active}
    except Exception as exc:
        await tg_text(chat_id, "⚠️ ضبط تموم شده ولی ارسالش به تلگرام خطا خورد. فایل فعلاً فقط توی حافظه موقت نگه داشته شده تا بتونم دوباره بفرستم.")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/internal/recording-ready")
async def recording_ready(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    raw_path = Path(str(data.get("filePath", ""))).resolve()
    return await _process_recording(data, raw_path)


@app.post("/internal/recording-upload")
async def recording_upload(
    request: Request,
    x_beonmeet_secret: str = Header(...),
    x_beonmeet_meta: str = Header(...),
) -> dict[str, Any]:
    """Receive a recording stream from a recorder worker.

    This removes the shared-filesystem requirement, so recorder workers can live
    on separate servers later. Existing local-path delivery remains supported by
    /internal/recording-ready as a rollback path.
    """
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        padded = x_beonmeet_meta + "=" * (-len(x_beonmeet_meta) % 4)
        meta = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid recording metadata")

    suffix = Path(str(meta.get("filename") or "recording.webm")).suffix or ".webm"
    raw_path = (RECORDING_ROOT / f"remote-{uuid.uuid4().hex}{suffix}").resolve()
    try:
        raw_path.relative_to(RECORDING_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recording path")

    received = 0
    try:
        with raw_path.open("wb") as fp:
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                fp.write(chunk)
        if received <= 0:
            raise HTTPException(status_code=400, detail="Empty recording upload")

        expected = int(meta.get("size") or 0)
        if expected and expected != received:
            raise HTTPException(
                status_code=400,
                detail=f"Recording size mismatch: expected {expected}, received {received}",
            )

        meta["filePath"] = str(raw_path)
        meta["size"] = received
        return await _process_recording(meta, raw_path)
    except Exception:
        raw_path.unlink(missing_ok=True)
        raise
