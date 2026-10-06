import asyncio
import base64
import json
import os
import re
import secrets
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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from state_store import DurableStateStore
from db_compat import is_postgres
from hetzner_autoscaler import router as autoscaler_router, autoscale_loop, enabled as autoscaler_enabled, profile_status
from scaling_policy import order_queue
from i18n import (
    BUTTON_ACTIONS,
    LANGUAGE_BUTTONS,
    SUPPORTED_LANGUAGES,
    menu as i18n_menu,
    normalize_language,
    profile as i18n_profile,
    tr as i18n_tr,
)

from admin_panel import (
    PLANS,
    activate_subscription,
    create_payment_intent,
    find_recording_for_artifact,
    free_recording_entitlement,
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
    was_premium_at,
)

app = FastAPI(title="BeOnMeet Controller")
app.include_router(admin_router)
app.include_router(autoscaler_router)

DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
TOKEN_FILE = DATA_DIR / "google-token.json"
USER_TOKEN_DIR = DATA_DIR / "google-tokens"
USER_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
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
DOWNLOAD_ROOT = DATA_DIR / "recording-downloads"
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
FREE_DOWNLOAD_TTL_HOURS = max(
    1,
    int(os.environ.get("FREE_DOWNLOAD_TTL_HOURS", os.environ.get("DOWNLOAD_TTL_HOURS", "24"))),
)
PREMIUM_DOWNLOAD_TTL_HOURS = max(1, int(os.environ.get("PREMIUM_DOWNLOAD_TTL_HOURS", "72")))
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
LEGACY_SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
PERSONAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
SCOPES = LEGACY_SCOPES

state_lock = asyncio.Lock()
queue_mutation_lock = asyncio.Lock()
worker_health_cache: dict[str, bool] = {}
remote_worker_cache: dict[str, dict[str, Any]] = {}
_whisper_model = None
_whisper_recovery_model = None
active_delivery_jobs = 0
delivery_locks: dict[str, asyncio.Lock] = {}
premium_recovery_tasks: dict[str, asyncio.Task[Any]] = {}
state: dict[str, Any] = {
    "telegram_offset": 0,
    "requests": {},
    "launched_events": {},
    "join_queue": [],
    "remote_claims": {},
    "oauth_state": None,
    "oauth_states": {},
    "auto_join_all": {},
    "auto_registered_events": {},
    "user_languages": {},
    "pending_deliveries": {},
    "recording_downloads": {},
    "premium_recoveries": {},
    "free_limit_notified": {},
}


def load_state() -> None:
    global state
    loaded, source = STATE_STORE.load()
    if isinstance(loaded, dict):
        state.update(loaded)
    state.setdefault("join_queue", [])
    state.setdefault("requests", {})
    state.setdefault("launched_events", {})
    state.setdefault("remote_claims", {})
    state.setdefault("telegram_offset", 0)
    state.setdefault("oauth_state", None)
    state.setdefault("oauth_states", {})
    state.setdefault("auto_join_all", {})
    state.setdefault("auto_registered_events", {})
    state.setdefault("user_languages", {})
    state.setdefault("pending_deliveries", {})
    state.setdefault("recording_downloads", {})
    state.setdefault("premium_recoveries", {})
    state.setdefault("free_limit_notified", {})
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


def user_language(chat_id: int | str) -> str:
    return normalize_language(
        str(state.setdefault("user_languages", {}).get(str(chat_id)) or ""),
        default="en",
    )


async def set_user_language(chat_id: int | str, language: str) -> str:
    lang = normalize_language(language)
    state.setdefault("user_languages", {})[str(chat_id)] = lang
    await save_state()
    return lang


def t(chat_id: int | str, key: str, **kwargs: Any) -> str:
    return i18n_tr(user_language(chat_id), key, **kwargs)


def telegram_reply_keyboard(chat_id: int | str) -> dict[str, Any]:
    labels = i18n_menu(user_language(chat_id))
    rows = [
        [{"text": labels["new"]}, {"text": labels["premium"]}],
        [{"text": labels["now"]}, {"text": labels["auto"]}],
        [{"text": labels["help"]}, {"text": labels["language"]}],
    ]
    if ADMINUSER and str(chat_id) == ADMINUSER:
        rows.append([{"text": labels["admin"]}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": labels["placeholder"],
    }


def telegram_language_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [[
            {"text": LANGUAGE_BUTTONS["fa"]},
            {"text": LANGUAGE_BUTTONS["en"]},
            {"text": LANGUAGE_BUTTONS["de"]},
        ]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


async def tg_text(
    chat_id: int | str,
    text: str,
    with_menu: bool = False,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    data: dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    elif with_menu:
        data["reply_markup"] = json.dumps(telegram_reply_keyboard(chat_id), ensure_ascii=False)
    await telegram("sendMessage", data)


async def send_subscription_offer(chat_id: int | str, message_key: str = "premium_offer") -> None:
    intents: dict[str, dict[str, Any]] = {}
    for plan_code in ("monthly", "quarterly", "halfyear"):
        intents[plan_code] = await asyncio.to_thread(
            create_payment_intent, str(chat_id), plan_code
        )

    lang = user_language(chat_id)
    keyboard = {
        "inline_keyboard": [
            [{
                "text": i18n_tr(lang, "plan_monthly"),
                "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['monthly']['intent']}",
            }],
            [{
                "text": i18n_tr(lang, "plan_quarterly"),
                "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['quarterly']['intent']}",
            }],
            [{
                "text": i18n_tr(lang, "plan_halfyear"),
                "url": f"https://pay.hamooncloud.ir/payments/beonmeet/start?intent={intents['halfyear']['intent']}",
            }],
        ]
    }
    await telegram(
        "sendMessage",
        {
            "chat_id": str(chat_id),
            "text": t(chat_id, message_key),
            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
        },
    )


async def setup_telegram_profile() -> None:
    try:
        for lang in SUPPORTED_LANGUAGES:
            profile = i18n_profile(lang)
            language_payload = {"language_code": lang}
            await telegram("setMyDescription", {
                **language_payload,
                "description": profile["description"],
            })
            await telegram("setMyShortDescription", {
                **language_payload,
                "short_description": profile["short"],
            })
            public_commands = [
                {"command": "start", "description": profile["commands"]["start"]},
                {"command": "plans", "description": profile["commands"]["plans"]},
                {"command": "now", "description": profile["commands"]["now"]},
                {"command": "auto", "description": profile["commands"]["auto"]},
                {"command": "language", "description": profile["commands"]["language"]},
            ]
            await telegram("setMyCommands", {
                "scope": json.dumps({"type": "all_private_chats"}),
                "language_code": lang,
                "commands": json.dumps(public_commands, ensure_ascii=False),
            })

        # English is the neutral default when Telegram does not provide a language.
        default_profile = i18n_profile("en")
        await telegram("setMyDescription", {
            "description": default_profile["description"],
        })
        await telegram("setMyShortDescription", {
            "short_description": default_profile["short"],
        })
        default_commands = [
            {"command": "start", "description": default_profile["commands"]["start"]},
            {"command": "plans", "description": default_profile["commands"]["plans"]},
            {"command": "now", "description": default_profile["commands"]["now"]},
            {"command": "auto", "description": default_profile["commands"]["auto"]},
            {"command": "language", "description": default_profile["commands"]["language"]},
        ]
        await telegram("setMyCommands", {
            "scope": json.dumps({"type": "all_private_chats"}),
            "commands": json.dumps(default_commands, ensure_ascii=False),
        })
        await telegram("setChatMenuButton", {
            "menu_button": json.dumps({"type": "commands"})
        })

        if ADMINUSER:
            for lang in SUPPORTED_LANGUAGES:
                profile = i18n_profile(lang)
                admin_commands = [
                    {"command": "start", "description": profile["commands"]["start"]},
                    {"command": "plans", "description": profile["commands"]["plans"]},
                    {"command": "now", "description": profile["commands"]["now"]},
                    {"command": "auto", "description": profile["commands"]["auto"]},
                    {"command": "language", "description": profile["commands"]["language"]},
                    {"command": "admin", "description": profile["commands"]["admin"]},
                ]
                await telegram("setMyCommands", {
                    "scope": json.dumps({"type": "chat", "chat_id": int(ADMINUSER)}),
                    "language_code": lang,
                    "commands": json.dumps(admin_commands, ensure_ascii=False),
                })
            await telegram("setChatMenuButton", {
                "chat_id": int(ADMINUSER),
                "menu_button": json.dumps({"type": "commands"}),
            })
    except Exception as exc:
        print("telegram profile setup error:", repr(exc), flush=True)


def google_flow(
    state_value: str | None = None,
    scopes: list[str] | None = None,
) -> Flow:
    cfg = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        cfg,
        scopes=scopes or LEGACY_SCOPES,
        state=state_value,
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def _safe_chat_id(chat_id: int | str) -> str:
    value = str(chat_id or "").strip()
    if not re.fullmatch(r"-?\d{1,20}", value):
        raise ValueError("invalid Telegram chat id")
    return value


def google_token_file(chat_id: int | str) -> Path:
    return USER_TOKEN_DIR / f"{_safe_chat_id(chat_id)}.json"


def _calendar_token_path(chat_id: int | str | None = None) -> Path:
    if chat_id is None:
        return TOKEN_FILE
    # Personal calendar features must always use the OAuth token created for
    # this exact Telegram user. Never fall back to the legacy shared bot token.
    return google_token_file(chat_id)


def personal_calendar_scopes_ready(chat_id: int | str) -> bool:
    path = google_token_file(chat_id)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
        granted = set(payload.get("scopes") or [])
    except Exception:
        return False
    return set(PERSONAL_SCOPES).issubset(granted)


def calendar_connected(chat_id: int | str | None = None) -> bool:
    token_path = _calendar_token_path(chat_id)
    if not token_path.exists():
        return False
    if chat_id is not None and token_path == google_token_file(chat_id):
        return personal_calendar_scopes_ready(chat_id)
    return True


def auto_join_enabled(chat_id: int | str) -> bool:
    return bool(state.setdefault("auto_join_all", {}).get(str(chat_id)))


def calendar_auth_url(chat_id: int | str) -> str:
    return f"https://{DOMAIN}/auth/google?chat_id={quote(_safe_chat_id(chat_id))}"


def load_google_credentials(chat_id: int | str | None = None) -> Credentials | None:
    token_path = _calendar_token_path(chat_id)
    if not token_path.exists():
        return None
    scopes = PERSONAL_SCOPES if chat_id is not None and token_path == google_token_file(chat_id) else LEGACY_SCOPES
    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        token_path.write_text(creds.to_json())
    return creds


def _calendar_entries(service: Any, *, all_calendars: bool) -> list[dict[str, Any]]:
    if not all_calendars:
        return [{"id": "primary", "primary": True}]

    entries: list[dict[str, Any]] = []
    page_token = None
    while True:
        result = service.calendarList().list(
            maxResults=250,
            pageToken=page_token,
            showDeleted=False,
            showHidden=True,
        ).execute()
        for item in result.get("items", []):
            calendar_id = str(item.get("id") or "").strip()
            if calendar_id and not item.get("deleted"):
                entries.append(item)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return entries


def list_calendar_events(
    chat_id: int | str | None = None,
    *,
    all_calendars: bool | None = None,
) -> list[dict[str, Any]]:
    creds = load_google_credentials(chat_id)
    if not creds:
        return []
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.now(timezone.utc)
    if all_calendars is None:
        all_calendars = chat_id is not None

    default_tz = None
    try:
        default_tz = service.settings().get(setting="timezone").execute().get("value")
    except Exception:
        pass

    events: list[dict[str, Any]] = []
    for calendar in _calendar_entries(service, all_calendars=bool(all_calendars)):
        calendar_id = str(calendar.get("id") or "primary")
        calendar_tz = str(calendar.get("timeZone") or default_tz or "")
        page_token = None
        try:
            while True:
                result = service.events().list(
                    calendarId=calendar_id,
                    timeMin=(now - timedelta(minutes=30)).isoformat(),
                    timeMax=(now + timedelta(days=14)).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                ).execute()
                for source_event in result.get("items", []):
                    event = dict(source_event)
                    event["_calendarId"] = calendar_id
                    event["_calendarSummary"] = str(calendar.get("summaryOverride") or calendar.get("summary") or "")
                    if calendar_tz:
                        event["_calendarTimeZone"] = calendar_tz
                    events.append(event)
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        except Exception as exc:
            print(f"calendar events skipped ({calendar_id}):", repr(exc), flush=True)
            continue
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


def event_declined_by_owner(event: dict[str, Any]) -> bool:
    for attendee in event.get("attendees", []) or []:
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return True
    return False


def find_calendar_event_for_meet(
    meet_url: str,
    chat_id: int | str | None = None,
) -> dict[str, Any] | None:
    events: list[dict[str, Any]] = []
    personal_path = None
    if chat_id is not None:
        try:
            personal_path = google_token_file(chat_id)
        except ValueError:
            personal_path = None
        if personal_path and personal_path.exists() and personal_calendar_scopes_ready(chat_id):
            events.extend(list_calendar_events(chat_id))
    # Keep the original shared bot-calendar lookup as a fallback so existing
    # manually registered meetings continue to work unchanged.
    if TOKEN_FILE.exists():
        events.extend(list_calendar_events())
    elif chat_id is not None and calendar_connected(chat_id):
        events.extend(list_calendar_events(chat_id))

    matches = [event for event in events if event_meet_url(event) == meet_url]
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
        return "—"
    tz_name = _event_timezone_name(event, "start")
    tz_label = f" ({tz_name})" if tz_name else ""
    if end:
        return f"{start.strftime('%Y-%m-%d %H:%M')} – {end.strftime('%H:%M')}{tz_label}"
    return f"{start.strftime('%Y-%m-%d %H:%M')}{tz_label}"


def _queue_event_id(event: dict[str, Any]) -> str:
    return str(event.get("id") or "")


def _is_queued(event_id: str) -> bool:
    return any(str(item.get("event_id") or "") == str(event_id) for item in state.get("join_queue", []))


def _queue_position(event_id: str, premium: bool) -> int:
    queue = state.get("join_queue", [])
    ordered = order_queue(queue)
    matching = [
        item for item in ordered
        if bool(item.get("premium")) == bool(premium)
    ]
    for idx, item in enumerate(matching, 1):
        if str(item.get("event_id") or "") == str(event_id):
            return idx
    return len(matching) + 1


def _pending_free_recordings(chat_id: str, exclude_event_id: str = "") -> int:
    """Count free recordings already reserved in queue or actively being processed."""
    event_ids: set[str] = set()

    for item in state.get("join_queue", []):
        if bool(item.get("premium")):
            continue
        req = item.get("req") or {}
        if str(req.get("chat_id") or "") != str(chat_id):
            continue
        event_id = str(item.get("event_id") or "")
        if event_id and event_id != exclude_event_id:
            event_ids.add(event_id)

    active_statuses = {"remote_claimed", "joining", "waiting_for_admission", "recording", "delivering"}
    for event_id, launched in state.get("launched_events", {}).items():
        if bool((launched or {}).get("premium")):
            continue
        if str((launched or {}).get("chat_id") or "") != str(chat_id):
            continue
        if str(event_id) == exclude_event_id:
            continue
        if str((launched or {}).get("status") or "joining") in active_statuses:
            event_ids.add(str(event_id))

    return len(event_ids)


async def _free_recording_allowed(
    chat_id: str,
    *,
    event_id: str = "",
    include_pending: bool = True,
    notify: bool = True,
) -> bool:
    entitlement = await asyncio.to_thread(free_recording_entitlement, str(chat_id))
    if entitlement.get("premium"):
        return True

    used = int(entitlement.get("used") or 0)
    limit = int(entitlement.get("limit") or 0)
    pending = _pending_free_recordings(str(chat_id), exclude_event_id=event_id) if include_pending else 0
    if used + pending < limit:
        return True

    if notify:
        notification_key = f"{chat_id}:{event_id}" if event_id else ""
        notified = state.setdefault("free_limit_notified", {})
        if not notification_key or notification_key not in notified:
            await send_subscription_offer(chat_id, "free_limit_reached")
            if notification_key:
                notified[notification_key] = datetime.now(timezone.utc).isoformat()
                await save_state()
    return False


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
        await tg_text(chat_id, t(chat_id, "queue_premium", position=position))
    else:
        await tg_text(chat_id, t(chat_id, "queue_free", position=position))


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
    event_id = _queue_event_id(event)
    if not premium and not await _free_recording_allowed(
        chat_id,
        event_id=event_id,
        include_pending=True,
        notify=True,
    ):
        return False

    launched, busy, pool_name = await _dispatch_meeting(
        event, req, meet_url, premium
    )
    if launched:
        if notify_start:
            if premium and pool_name.startswith("premium-"):
                await tg_text(chat_id, t(chat_id, "launch_premium", meet_url=meet_url))
            elif premium:
                await tg_text(chat_id, t(chat_id, "launch_priority", meet_url=meet_url))
            else:
                await tg_text(chat_id, t(chat_id, "launch_free", meet_url=meet_url))
        return True

    if busy and queue_if_busy:
        await enqueue_meeting(event, req, meet_url, premium, notify=True)
        return False

    if not busy and notify_start:
        await tg_text(chat_id, t(chat_id, "dispatch_retry", meet_url=meet_url))
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
            # A remote worker claim is a short lease. If a worker disappears before
            # acknowledging the job, put it safely back in the queue.
            now_utc = datetime.now(timezone.utc)
            expired_claims: list[str] = []
            for claim_id, claim in list(state.setdefault("remote_claims", {}).items()):
                claimed_at_raw = str(claim.get("claimed_at") or "")
                try:
                    claimed_at = isoparse(claimed_at_raw) if claimed_at_raw else now_utc
                except Exception:
                    claimed_at = now_utc
                if now_utc - claimed_at > timedelta(seconds=90):
                    item = claim.get("item") or {}
                    event_id = str(item.get("event_id") or "")
                    launched = state.get("launched_events", {}).get(event_id) or {}
                    if launched.get("status") == "remote_claimed":
                        state["launched_events"].pop(event_id, None)
                    if event_id and not _is_queued(event_id):
                        state.setdefault("join_queue", []).append(item)
                    expired_claims.append(claim_id)
            if expired_claims:
                for claim_id in expired_claims:
                    state["remote_claims"].pop(claim_id, None)
                await save_state()

            queue = state.setdefault("join_queue", [])
            if queue:
                ordered = order_queue(queue)
                for item in ordered:
                    event_id = str(item.get("event_id") or "")
                    if event_id and not _is_queued(event_id):
                        continue
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
                        await tg_text(chat_id, t(chat_id, "queue_expired"))
                        continue

                    # Serialize local queue dispatch with remote worker claims.
                    # Without this lock, a remote worker and the local pool could
                    # pick the same meeting at exactly the same moment.
                    async with queue_mutation_lock:
                        if event_id and not _is_queued(event_id):
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

                    if launched:
                        if premium:
                            await tg_text(chat_id, t(chat_id, "premium_ready", meet_url=meet_url))
                        else:
                            await tg_text(chat_id, t(chat_id, "queue_ready", meet_url=meet_url))
                    elif not busy:
                        # Transient dispatch/network error. Keep the queue item and retry.
                        continue
        except Exception as exc:
            print("queue loop error:", repr(exc), flush=True)
        await asyncio.sleep(3)


async def state_cleanup_loop() -> None:
    while True:
        try:
            now = datetime.now(timezone.utc)
            changed = False

            # Telegram request mappings are only needed for nearby meetings and
            # recording metadata. Keeping 30 days is generous and prevents
            # unbounded controller-state growth as the user base grows.
            requests = state.setdefault("requests", {})
            for meet_url, req in list(requests.items()):
                raw = str((req or {}).get("requested_at") or "")
                try:
                    created = isoparse(raw) if raw else now
                except Exception:
                    created = now
                if now - created > timedelta(days=30):
                    requests.pop(meet_url, None)
                    changed = True

            downloads = state.setdefault("recording_downloads", {})
            for token, item in list(downloads.items()):
                expires_raw = str((item or {}).get("expires_at") or "")
                try:
                    expires_at = isoparse(expires_raw) if expires_raw else now
                except Exception:
                    expires_at = now
                if now >= expires_at:
                    file_path = Path(str((item or {}).get("file_path") or ""))
                    try:
                        file_path.relative_to(DOWNLOAD_ROOT)
                        file_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    downloads.pop(token, None)
                    changed = True

            # Finished/stale launch records have no purpose after two days.
            launched_events = state.setdefault("launched_events", {})
            for event_id, launched in list(launched_events.items()):
                raw = str(
                    launched.get("recording_started_at")
                    or launched.get("waiting_since")
                    or launched.get("launched_at")
                    or ""
                )
                try:
                    created = isoparse(raw) if raw else now
                except Exception:
                    created = now
                if now - created > timedelta(days=2):
                    launched_events.pop(event_id, None)
                    changed = True

            free_limit_notified = state.setdefault("free_limit_notified", {})
            for key, raw in list(free_limit_notified.items()):
                try:
                    created = isoparse(str(raw)) if raw else now
                except Exception:
                    created = now
                if now - created > timedelta(days=2):
                    free_limit_notified.pop(key, None)
                    changed = True

            auto_registered = state.setdefault("auto_registered_events", {})
            for key, raw in list(auto_registered.items()):
                try:
                    created = isoparse(str(raw)) if raw else now
                except Exception:
                    created = now
                if now - created > timedelta(days=30):
                    auto_registered.pop(key, None)
                    changed = True

            oauth_states = state.setdefault("oauth_states", {})
            for key, item in list(oauth_states.items()):
                raw = str((item or {}).get("created_at") or "")
                try:
                    created = isoparse(raw) if raw else now
                except Exception:
                    created = now
                if now - created > timedelta(hours=1):
                    oauth_states.pop(key, None)
                    changed = True

            if changed:
                await save_state()
        except Exception as exc:
            print("state cleanup loop error:", repr(exc), flush=True)

        await asyncio.sleep(600)


def same_meeting_inflight(
    chat_id: int | str,
    meet_url: str,
    event_id: str,
    now: datetime,
) -> bool:
    target_chat = str(chat_id)
    for item in state.get("join_queue", []):
        if str(item.get("event_id") or "") == event_id:
            continue
        req = item.get("req") or {}
        if (
            str(req.get("chat_id") or "") == target_chat
            and str(item.get("meet_url") or "") == meet_url
        ):
            return True

    for other_event_id, launched in state.get("launched_events", {}).items():
        if str(other_event_id) == event_id:
            continue
        if (
            str(launched.get("chat_id") or "") != target_chat
            or str(launched.get("meet_url") or "") != meet_url
        ):
            continue
        status = str(launched.get("status") or "joining")
        if status in {"recording", "waiting_for_admission", "delivering", "remote_claimed"}:
            return True
        launched_at_raw = str(launched.get("launched_at") or "")
        try:
            launched_at = isoparse(launched_at_raw) if launched_at_raw else None
        except Exception:
            launched_at = None
        if launched_at and now - launched_at < timedelta(minutes=7):
            return True
    return False


async def maybe_launch_calendar_event(
    event: dict[str, Any],
    req: dict[str, Any],
    meet_url: str,
    now: datetime,
) -> bool:
    event_id = str(event.get("id") or "")
    if not event_id or _is_queued(event_id):
        return False
    if same_meeting_inflight(req.get("chat_id") or "", meet_url, event_id, now):
        return False

    launched = state["launched_events"].get(event_id)
    if launched:
        status = str(launched.get("status") or "joining")
        launched_at_raw = launched.get("launched_at")
        launched_at = isoparse(launched_at_raw) if launched_at_raw else None
        if status in {"recording", "waiting_for_admission", "delivering"}:
            return False
        if launched_at and now - launched_at < timedelta(minutes=7):
            return False
        state["launched_events"].pop(event_id, None)
        await save_state()

    start = event_start(event)
    end = event_end(event)
    if not start:
        return False
    if end and now > end:
        return False
    live_until = (end + timedelta(minutes=5)) if end else (start + timedelta(hours=3))
    if not (start <= now <= live_until):
        return False

    await launch_meeting(event, req, meet_url)
    return True


async def calendar_loop() -> None:
    while True:
        try:
            now = datetime.now(timezone.utc)

            # Legacy/manual mode: retain the shared recorder calendar behavior.
            if TOKEN_FILE.exists():
                events = await asyncio.to_thread(list_calendar_events)
                for event in events:
                    meet_url = event_meet_url(event)
                    if not meet_url:
                        continue
                    req = state["requests"].get(meet_url)
                    if not req:
                        continue
                    await maybe_launch_calendar_event(event, req, meet_url, now)

            # Personal auto mode: once enabled, every Google Meet on that user's
            # connected calendar is discovered and launched without sending links.
            auto_settings = dict(state.setdefault("auto_join_all", {}))
            for chat_id, enabled in auto_settings.items():
                if not enabled or not calendar_connected(chat_id):
                    continue
                if not await asyncio.to_thread(is_premium, str(chat_id)):
                    continue
                try:
                    events = await asyncio.to_thread(list_calendar_events, chat_id)
                except Exception as exc:
                    print(f"calendar auto lookup error ({chat_id}):", repr(exc), flush=True)
                    continue

                for source_event in events:
                    if source_event.get("status") == "cancelled" or event_declined_by_owner(source_event):
                        continue
                    meet_url = event_meet_url(source_event)
                    original_event_id = str(source_event.get("id") or "")
                    if not meet_url or not original_event_id:
                        continue

                    start = event_start(source_event)
                    end = event_end(source_event)
                    if not start:
                        continue
                    live_until = (end + timedelta(minutes=5)) if end else (start + timedelta(hours=3))
                    if not (start <= now <= live_until):
                        continue

                    calendar_id = str(source_event.get("_calendarId") or "primary")
                    stable_event_key = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"beonmeet:{chat_id}:{calendar_id}:{original_event_id}",
                        )
                    )
                    event = dict(source_event)
                    event["google_event_id"] = original_event_id
                    event["google_calendar_id"] = calendar_id
                    event["id"] = f"auto-{stable_event_key}"
                    req = {
                        "chat_id": str(chat_id),
                        "requester_id": str(chat_id),
                        "ui_language": user_language(chat_id),
                        "requested_at": now.isoformat(),
                        "auto_calendar": True,
                    }

                    registered = state.setdefault("auto_registered_events", {})
                    if event["id"] not in registered:
                        await asyncio.to_thread(record_request, str(chat_id), meet_url, "auto_calendar")
                        registered[event["id"]] = now.isoformat()
                        await save_state()

                    await maybe_launch_calendar_event(event, req, meet_url, now)
        except Exception as exc:
            print("calendar loop error:", repr(exc), flush=True)
        await asyncio.sleep(CALENDAR_POLL_SECONDS)


async def telegram_loop() -> None:
    while True:
        try:
            offset = int(state.get("telegram_offset") or 0)
            url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=20.0)) as client:
                r = await client.post(
                    url,
                    data={
                        "timeout": 30,
                        "offset": offset,
                        "allowed_updates": json.dumps(["message"]),
                    },
                )
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

                # Choose an initial UI language from Telegram once, then persist the
                # user's explicit choice independently from meeting/transcript language.
                user_languages = state.setdefault("user_languages", {})
                if str(chat_id) not in user_languages:
                    user_languages[str(chat_id)] = normalize_language(
                        str(from_user.get("language_code") or ""),
                        default="en",
                    )
                    await save_state()

                mapped_action = BUTTON_ACTIONS.get(text)
                if mapped_action:
                    text = mapped_action

                if text.startswith("/setlanguage"):
                    parts = text.split(maxsplit=1)
                    requested = parts[1] if len(parts) > 1 else "en"
                    await set_user_language(chat_id, requested)
                    await tg_text(chat_id, t(chat_id, "language_changed"), with_menu=True)
                    continue

                if text.startswith("/language"):
                    await tg_text(
                        chat_id,
                        t(chat_id, "language_choose"),
                        reply_markup=telegram_language_keyboard(),
                    )
                    continue

                if text.startswith("/new"):
                    await tg_text(chat_id, t(chat_id, "new_prompt"), with_menu=True)
                    continue

                if text.startswith("/admin"):
                    if ADMINUSER and str(chat_id) == ADMINUSER:
                        await tg_text(
                            chat_id,
                            t(chat_id, "admin_ready", url=make_admin_login_url()),
                        )
                    else:
                        await tg_text(chat_id, t(chat_id, "admin_only"))
                    continue

                if text.startswith("/plans") or text.startswith("/premium"):
                    info = await asyncio.to_thread(subscription_info, str(chat_id))
                    if info.get("premium"):
                        until = info.get("until")
                        until_text = until.astimezone().strftime("%Y-%m-%d") if until else ""
                        await tg_text(
                            chat_id,
                            t(chat_id, "premium_active", until=until_text),
                            with_menu=True,
                        )
                    else:
                        await send_subscription_offer(chat_id)
                    continue

                if text.startswith("/auto"):
                    parts = text.strip().lower().split(maxsplit=1)
                    explicit = parts[1] if len(parts) > 1 else ""

                    # Turning the feature off is always allowed, even after Premium expires.
                    if explicit in {"off", "0", "false", "disable"}:
                        state.setdefault("auto_join_all", {})[str(chat_id)] = False
                        await save_state()
                        await tg_text(chat_id, t(chat_id, "auto_disabled"), with_menu=True)
                        continue

                    if not await asyncio.to_thread(is_premium, str(chat_id)):
                        await send_subscription_offer(chat_id, "auto_premium_only")
                        continue

                    if not calendar_connected(chat_id):
                        await tg_text(
                            chat_id,
                            t(chat_id, "auto_connect", url=calendar_auth_url(chat_id)),
                            with_menu=True,
                        )
                        continue

                    if explicit in {"on", "1", "true", "enable"}:
                        enabled = True
                    else:
                        enabled = not auto_join_enabled(chat_id)
                    state.setdefault("auto_join_all", {})[str(chat_id)] = enabled
                    await save_state()
                    await tg_text(
                        chat_id,
                        t(chat_id, "auto_enabled" if enabled else "auto_disabled"),
                        with_menu=True,
                    )
                    continue

                if text.startswith("/start"):
                    premium_active = await asyncio.to_thread(is_premium, str(chat_id))
                    if not premium_active:
                        auth_status = t(chat_id, "auto_premium_status")
                    elif calendar_connected(chat_id):
                        auth_status = t(chat_id, "calendar_connected")
                        auth_status += "\n" + t(
                            chat_id,
                            "auto_status_on" if auto_join_enabled(chat_id) else "auto_status_off",
                        )
                    else:
                        auth_status = t(
                            chat_id,
                            "calendar_disconnected",
                            url=calendar_auth_url(chat_id),
                        )
                    await tg_text(
                        chat_id,
                        t(
                            chat_id,
                            "start",
                            bot_email=BOT_EMAIL,
                            auth_status=auth_status,
                        ),
                        with_menu=True,
                    )
                    continue

                if text.strip().lower() == "/now":
                    if not await _free_recording_allowed(
                        str(chat_id),
                        include_pending=True,
                        notify=True,
                    ):
                        continue
                    state.setdefault("pending_now", {})[str(chat_id)] = True
                    await save_state()
                    await tg_text(chat_id, t(chat_id, "now_prompt"), with_menu=True)
                    continue

                force_now = text.strip().lower().startswith("/now") or bool(
                    state.setdefault("pending_now", {}).pop(str(chat_id), False)
                )
                meet_url = normalize_meet_url(text)
                if meet_url:
                    if not await _free_recording_allowed(
                        str(chat_id),
                        include_pending=False,
                        notify=True,
                    ):
                        continue
                    state["requests"][meet_url] = {
                        "chat_id": str(chat_id),
                        "requester_id": str(from_user.get("id") or chat_id),
                        "first_name": from_user.get("first_name") or chat.get("first_name") or "",
                        "last_name": from_user.get("last_name") or chat.get("last_name") or "",
                        "username": from_user.get("username") or chat.get("username") or "",
                        "ui_language": user_language(chat_id),
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await save_state()
                    await asyncio.to_thread(
                        record_request,
                        str(chat_id),
                        meet_url,
                        "now" if force_now else "calendar",
                    )

                    if force_now:
                        synthetic_event = {
                            "id": f"manual-{uuid.uuid4()}",
                            "start": {"dateTime": datetime.now(timezone.utc).isoformat()},
                            "end": {
                                "dateTime": (
                                    datetime.now(timezone.utc) + timedelta(hours=3)
                                ).isoformat()
                            },
                        }
                        await launch_meeting(
                            synthetic_event,
                            state["requests"][meet_url],
                            meet_url,
                        )
                        continue

                    try:
                        matched_event = await asyncio.to_thread(
                            find_calendar_event_for_meet,
                            meet_url,
                            str(chat_id),
                        )
                    except Exception as exc:
                        print(
                            "calendar lookup error after Telegram request:",
                            repr(exc),
                            flush=True,
                        )
                        await tg_text(chat_id, t(chat_id, "calendar_error"))
                        continue

                    if matched_event:
                        when = fmt_event_time(matched_event)
                        await tg_text(
                            chat_id,
                            t(
                                chat_id,
                                "event_found",
                                meet_url=meet_url,
                                when=when,
                            ),
                        )
                        now = datetime.now(timezone.utc)
                        start_at = event_start(matched_event)
                        end_at = event_end(matched_event)
                        live_until = (
                            end_at + timedelta(minutes=5)
                            if end_at
                            else (
                                start_at + timedelta(hours=3)
                                if start_at
                                else now
                            )
                        )
                        if start_at and start_at <= now <= live_until:
                            await launch_meeting(
                                matched_event,
                                state["requests"][meet_url],
                                meet_url,
                            )
                    else:
                        await tg_text(
                            chat_id,
                            t(
                                chat_id,
                                "event_missing",
                                bot_email=BOT_EMAIL,
                                meet_url=meet_url,
                            ),
                        )
                else:
                    await tg_text(chat_id, t(chat_id, "send_link"))
        except Exception as exc:
            print("telegram loop error:", repr(exc), flush=True)
            await asyncio.sleep(5)


async def recording_download_ttl_hours(owner_chat_id: str = "") -> int:
    if owner_chat_id and await asyncio.to_thread(is_premium, str(owner_chat_id)):
        return PREMIUM_DOWNLOAD_TTL_HOURS
    return FREE_DOWNLOAD_TTL_HOURS


async def create_recording_download(
    path: Path,
    filename: str,
    owner_chat_id: str = "",
) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    suffix = path.suffix.lower() if path.suffix else ".webm"
    stored_path = (DOWNLOAD_ROOT / f"{token}{suffix}").resolve()
    stored_path.relative_to(DOWNLOAD_ROOT)
    await asyncio.to_thread(shutil.copy2, path, stored_path)
    ttl_hours = await recording_download_ttl_hours(owner_chat_id)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=ttl_hours)
    state.setdefault("recording_downloads", {})[token] = {
        "file_path": str(stored_path),
        "filename": filename,
        "owner_chat_id": str(owner_chat_id or ""),
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_hours": ttl_hours,
    }
    await save_state()
    return f"https://{DOMAIN}/download/{token}", ttl_hours


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

    # The official Telegram Bot API caps uploaded files at 50 MB.
    # For larger recordings, avoid chat spam and provide one expiring full-file download.
    download_url, expires_hours = await create_recording_download(
        path,
        filename,
        owner_chat_id=str(recipients[0]["chat_id"]) if recipients else "",
    )
    for target in recipients:
        await tg_text(
            target["chat_id"],
            t(
                target["chat_id"],
                "large_video_download",
                url=download_url,
                hours=expires_hours,
            ),
        )


async def send_audio_to_recipients(
    recipients: list[dict[str, str]],
    path: Path,
    filename: str,
) -> None:
    """Deliver meeting audio without blocking downstream transcription.

    Telegram's official Bot API rejects uploads around 50 MB. Prefer a compact
    speech-friendly MP3 that normally fits, and fall back to an expiring secure
    download for unusually long meetings or transient upload-size failures.
    """
    max_cloud = 49 * 1024 * 1024
    size = path.stat().st_size
    download_url: str | None = None
    download_hours = FREE_DOWNLOAD_TTL_HOURS

    for target in recipients:
        if size <= max_cloud or TELEGRAM_API_BASE != "https://api.telegram.org":
            try:
                with path.open("rb") as fp:
                    await telegram(
                        "sendDocument",
                        {
                            "chat_id": target["chat_id"],
                            "caption": target["caption"],
                        },
                        {"document": (filename, fp, "audio/mpeg")},
                    )
                continue
            except Exception as exc:
                # Do not let one Telegram upload failure cancel transcription.
                print(
                    f"audio Telegram upload failed for {target['chat_id']}: {exc!r}",
                    flush=True,
                )

        if download_url is None:
            download_url, download_hours = await create_recording_download(
                path,
                filename,
                owner_chat_id=str(recipients[0]["chat_id"]) if recipients else "",
            )
        await tg_text(
            target["chat_id"],
            t(
                target["chat_id"],
                "large_audio_download",
                url=download_url,
                hours=download_hours,
            ),
        )


def _normalize_transcript_text(value: str) -> str:
    text_value = re.sub(r"\s+", " ", (value or "").strip())
    # Normalize common Arabic code points to Persian forms without translating
    # or otherwise changing the original language of the meeting.
    return (
        text_value
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
    )


def _audio_duration_seconds(audio_path: Path) -> float:
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return max(0.0, float(probe.stdout.strip() or "0"))
    except Exception:
        return 0.0


def transcribe_audio_local(audio_path: Path) -> tuple[str, str]:
    global _whisper_model
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        # large-v3 materially improves Persian and non-English accuracy. Keeping
        # concurrency at one protects the 16-vCPU production host from CPU spikes.
        model_name = os.environ.get("WHISPER_MODEL", "large-v3")
        _whisper_model = WhisperModel(
            model_name,
            device="cpu",
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            cpu_threads=max(6, min(14, (os.cpu_count() or 8) - 2)),
            num_workers=1,
            download_root=str(DATA_DIR / "whisper-models"),
        )

    duration = _audio_duration_seconds(audio_path)
    chunk_seconds = max(45, int(os.environ.get("TRANSCRIPTION_CHUNK_SECONDS", "120")))
    chunks: list[tuple[float, Path, bool]] = []

    if duration <= 0 or duration <= chunk_seconds * 1.25:
        chunks.append((0.0, audio_path, False))
    else:
        start_at = 0.0
        index = 0
        while start_at < duration:
            length = min(float(chunk_seconds), duration - start_at)
            chunk_path = audio_path.with_name(
                f".{audio_path.stem}_transcribe_{index:04d}.wav"
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start_at:.3f}",
                    "-t",
                    f"{length:.3f}",
                    "-i",
                    str(audio_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(chunk_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            chunks.append((start_at, chunk_path, True))
            start_at += length
            index += 1

    lines: list[str] = []
    previous_text = ""
    language_stats: dict[str, list[float]] = {}

    try:
        for offset_seconds, chunk_path, _temporary in chunks:
            segments, info = _whisper_model.transcribe(
                str(chunk_path),
                task="transcribe",
                language=None,
                beam_size=7,
                best_of=5,
                patience=1.2,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 250,
                    "speech_pad_ms": 350,
                    "min_speech_duration_ms": 200,
                },
                condition_on_previous_text=True,
                multilingual=True,
                language_detection_threshold=0.45,
                language_detection_segments=10,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
            )

            language = str(getattr(info, "language", None) or "unknown")
            probability = float(
                getattr(info, "language_probability", 0.0) or 0.0
            )
            language_stats.setdefault(language, []).append(probability)

            for segment in segments:
                text_value = _normalize_transcript_text(segment.text or "")
                if not text_value:
                    continue
                # Whisper occasionally repeats the same sentence at a chunk
                # boundary. Suppress exact consecutive duplicates only.
                if text_value == previous_text:
                    continue
                previous_text = text_value
                absolute_start = offset_seconds + float(segment.start or 0.0)
                minutes = int(absolute_start // 60)
                seconds = int(absolute_start % 60)
                lines.append(f"[{minutes:02d}:{seconds:02d}] {text_value}")
    finally:
        for _offset, chunk_path, temporary in chunks:
            if temporary:
                chunk_path.unlink(missing_ok=True)

    detected = []
    for language, probabilities in sorted(
        language_stats.items(),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        average = sum(probabilities) / max(1, len(probabilities))
        detected.append(f"{language} ({average * 100:.0f}%)")

    language_label = ", ".join(detected) if detected else "auto"
    return "\n".join(lines).strip(), language_label



def transcribe_audio_recovery_fast(audio_path: Path) -> tuple[str, str]:
    """Faster CPU fallback for Premium transcription and retained-file recovery."""
    global _whisper_recovery_model
    from faster_whisper import WhisperModel

    if _whisper_recovery_model is None:
        model_name = os.environ.get("RECOVERY_WHISPER_MODEL", "small")
        _whisper_recovery_model = WhisperModel(
            model_name,
            device="cpu",
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            cpu_threads=max(6, min(14, (os.cpu_count() or 8) - 2)),
            num_workers=1,
            download_root=str(DATA_DIR / "whisper-models"),
        )

    duration = _audio_duration_seconds(audio_path)
    chunk_seconds = max(180, int(os.environ.get("RECOVERY_TRANSCRIPTION_CHUNK_SECONDS", "600")))
    chunks: list[tuple[float, Path, bool]] = []

    if duration <= 0 or duration <= chunk_seconds * 1.25:
        chunks.append((0.0, audio_path, False))
    else:
        start_at = 0.0
        index = 0
        while start_at < duration:
            length = min(float(chunk_seconds), duration - start_at)
            chunk_path = audio_path.with_name(
                f".{audio_path.stem}_recovery_{index:04d}.wav"
            )
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", f"{start_at:.3f}",
                    "-t", f"{length:.3f}",
                    "-i", str(audio_path),
                    "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le",
                    str(chunk_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            chunks.append((start_at, chunk_path, True))
            start_at += length
            index += 1

    lines: list[str] = []
    previous_text = ""
    language_stats: dict[str, list[float]] = {}
    try:
        for offset_seconds, chunk_path, _temporary in chunks:
            segments, info = _whisper_recovery_model.transcribe(
                str(chunk_path),
                task="transcribe",
                language=None,
                beam_size=1,
                best_of=1,
                patience=1.0,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 300,
                    "min_speech_duration_ms": 200,
                },
                condition_on_previous_text=False,
                multilingual=True,
                language_detection_threshold=0.45,
                language_detection_segments=4,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
            )
            language = str(getattr(info, "language", None) or "unknown")
            probability = float(getattr(info, "language_probability", 0.0) or 0.0)
            language_stats.setdefault(language, []).append(probability)

            for segment in segments:
                text_value = _normalize_transcript_text(segment.text or "")
                if not text_value or text_value == previous_text:
                    continue
                previous_text = text_value
                absolute_start = offset_seconds + float(segment.start or 0.0)
                minutes = int(absolute_start // 60)
                seconds = int(absolute_start % 60)
                lines.append(f"[{minutes:02d}:{seconds:02d}] {text_value}")
    finally:
        for _offset, chunk_path, temporary in chunks:
            if temporary:
                chunk_path.unlink(missing_ok=True)

    detected = []
    for language, probabilities in sorted(
        language_stats.items(),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        average = sum(probabilities) / max(1, len(probabilities))
        detected.append(f"{language} ({average * 100:.0f}%)")

    return "\n".join(lines).strip(), (", ".join(detected) if detected else "auto")


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
    asyncio.create_task(state_cleanup_loop())
    asyncio.create_task(delivery_recovery_loop())
    asyncio.create_task(premium_upgrade_backfill_loop())
    asyncio.create_task(autoscale_loop())


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
            t(
                telegram_id,
                "payment_confirmed",
                until=until.astimezone().strftime("%Y-%m-%d"),
            )
        )
        if ADMINUSER and ADMINUSER != telegram_id:
            await tg_text(
                ADMINUSER,
                f"💳 خرید پلن ویژه\nکاربر: {telegram_id}\nپلن: {expected_plan}\nمبلغ: {expected_amount:,} تومان\nرسید: {receipt}"
            )

    return "<html lang='fa' dir='rtl'><meta charset='utf-8'><body style='font-family:tahoma;background:#0b0e17;color:white;display:grid;place-items:center;min-height:100vh;margin:0'><div style='text-align:center'><h2>پرداخت موفق بود ✅</h2><p>پلن ویژه فعال شد. می‌تونی این صفحه رو ببندی و برگردی تلگرام.</p></div></body></html>"


def _remote_worker_alive(entry: dict[str, Any]) -> bool:
    try:
        last_seen = isoparse(str(entry.get("last_seen") or ""))
        return datetime.now(timezone.utc) - last_seen <= timedelta(seconds=30)
    except Exception:
        return False


@app.post("/internal/worker/heartbeat")
async def remote_worker_heartbeat(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    worker_id = str(data.get("worker_id") or "").strip()
    pool = str(data.get("pool") or "free").strip().lower()
    slots = max(1, min(32, int(data.get("slots") or 1)))
    if not worker_id or pool not in {"free", "premium"}:
        raise HTTPException(status_code=400, detail="Invalid worker")
    active_jobs = max(0, int(data.get("active_jobs") or 0))
    max_jobs = max(1, int(data.get("max_jobs") or slots))
    available_slots = max(0, int(data.get("available_slots") or (max_jobs - active_jobs)))
    account_id = str(data.get("account_id") or "primary")
    worker_state = {
        "pool": pool,
        "slots": slots,
        "active_jobs": active_jobs,
        "max_jobs": max_jobs,
        "available_slots": available_slots,
        "account_id": account_id,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    remote_worker_cache[worker_id] = worker_state
    try:
        STATE_STORE.redis.setex(
            f"beonmeet:worker:{worker_id}",
            60,
            json.dumps(worker_state, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception as exc:
        print("remote worker heartbeat Redis error:", repr(exc), flush=True)
    return {"ok": True}


@app.post("/internal/worker/claim")
async def remote_worker_claim(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    worker_id = str(data.get("worker_id") or "").strip()
    pool = str(data.get("pool") or "free").strip().lower()
    slots = max(1, min(32, int(data.get("slots") or 1)))
    if not worker_id or pool not in {"free", "premium"}:
        raise HTTPException(status_code=400, detail="Invalid worker")

    existing_worker = remote_worker_cache.get(worker_id) or {}
    account_id = str(data.get("account_id") or existing_worker.get("account_id") or "primary")
    remote_worker_cache[worker_id] = {
        "pool": pool,
        "slots": slots,
        "active_jobs": int(existing_worker.get("active_jobs") or 0),
        "max_jobs": int(existing_worker.get("max_jobs") or slots),
        "available_slots": int(existing_worker.get("available_slots") or slots),
        "account_id": account_id,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }

    chosen: dict[str, Any] | None = None
    claim_id = ""
    async with queue_mutation_lock:
        queue = state.setdefault("join_queue", [])
        candidates = order_queue(queue)
        for item in candidates:
            premium = bool(item.get("premium"))
            # Reserved Premium workers only serve Premium. General workers may
            # take Premium overflow first, then free jobs.
            if pool == "premium" and not premium:
                continue
            event_id = str(item.get("event_id") or "")
            if not event_id or not _is_queued(event_id):
                continue
            chosen = item
            state["join_queue"] = [
                q for q in state.get("join_queue", [])
                if str(q.get("event_id") or "") != event_id
            ]
            claim_id = uuid.uuid4().hex
            state.setdefault("remote_claims", {})[claim_id] = {
                "item": item,
                "worker_id": worker_id,
                "pool": pool,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
            }
            req = item.get("req") or {}
            state.setdefault("launched_events", {})[event_id] = {
                "meet_url": item.get("meet_url"),
                "chat_id": str(req.get("chat_id") or ""),
                "launched_at": datetime.now(timezone.utc).isoformat(),
                "status": "remote_claimed",
                "premium": premium,
                "pool": f"remote:{worker_id}",
            }
            break

    if not chosen:
        return {"ok": True, "job": None}

    await save_state()
    req = chosen.get("req") or {}
    event_id = str(chosen.get("event_id") or "")
    premium = bool(chosen.get("premium"))
    return {
        "ok": True,
        "claim_id": claim_id,
        "job": {
            "bearerToken": "beonmeet-remote",
            "url": str(chosen.get("meet_url") or ""),
            "name": BOT_DISPLAY_NAME,
            "teamId": "beonmeet-premium" if premium else "beonmeet-free",
            "timezone": "UTC",
            "userId": str(req.get("chat_id") or ""),
            "eventId": event_id,
            "botId": event_id,
        },
    }


@app.post("/internal/worker/accepted")
async def remote_worker_accepted(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    claim_id = str(data.get("claim_id") or "").strip()
    claim = state.setdefault("remote_claims", {}).pop(claim_id, None)
    if not claim:
        return {"ok": True, "already_handled": True}

    item = claim.get("item") or {}
    event_id = str(item.get("event_id") or "")
    req = item.get("req") or {}
    chat_id = str(req.get("chat_id") or "")
    if event_id:
        launched = state.setdefault("launched_events", {}).setdefault(event_id, {})
        launched["status"] = "joining"
        launched["launched_at"] = datetime.now(timezone.utc).isoformat()
    await save_state()

    if chat_id:
        if bool(item.get("premium")):
            await tg_text(chat_id, t(chat_id, "premium_ready", meet_url=""))
        else:
            await tg_text(chat_id, t(chat_id, "queue_ready", meet_url=""))
    return {"ok": True}


@app.post("/internal/worker/requeue")
async def remote_worker_requeue(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    claim_id = str(data.get("claim_id") or "").strip()
    claim = state.setdefault("remote_claims", {}).pop(claim_id, None)
    if not claim:
        return {"ok": True, "already_handled": True}

    item = claim.get("item") or {}
    event_id = str(item.get("event_id") or "")
    if event_id:
        launched = state.setdefault("launched_events", {}).get(event_id) or {}
        if launched.get("status") in {"remote_claimed", "joining"}:
            state["launched_events"].pop(event_id, None)
        if not _is_queued(event_id):
            item["queued_at"] = datetime.now(timezone.utc).isoformat()
            state.setdefault("join_queue", []).append(item)
    await save_state()
    return {"ok": True}


@app.get("/download/{token}")
async def download_recording(token: str):
    item = state.setdefault("recording_downloads", {}).get(token)
    if not item:
        raise HTTPException(status_code=404, detail="Download not found or expired")
    expires_raw = str(item.get("expires_at") or "")
    try:
        expires_at = isoparse(expires_raw)
    except Exception:
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(status_code=410, detail="Download expired")
    file_path = Path(str(item.get("file_path") or "")).resolve()
    try:
        file_path.relative_to(DOWNLOAD_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="Download not found")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Download file missing")
    filename = str(item.get("filename") or file_path.name)
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


async def _resolve_download_owner(token: str, item: dict[str, Any], file_path: Path) -> str:
    owner_chat_id = str(item.get("owner_chat_id") or "").strip()
    if owner_chat_id:
        return owner_chat_id

    created_raw = str(item.get("created_at") or "").strip()
    if not created_raw:
        expires_raw = str(item.get("expires_at") or "").strip()
        try:
            ttl_hours = int(item.get("ttl_hours") or FREE_DOWNLOAD_TTL_HOURS)
            created_raw = (
                isoparse(expires_raw) - timedelta(hours=ttl_hours)
            ).isoformat()
        except Exception:
            created_raw = ""
    if not created_raw:
        raise HTTPException(status_code=409, detail="Recording identity is unavailable")

    recording = await asyncio.to_thread(
        find_recording_for_artifact,
        str(item.get("filename") or file_path.name),
        int(file_path.stat().st_size),
        created_raw,
        15,
    )
    if not recording:
        raise HTTPException(status_code=409, detail="Recording owner could not be resolved safely")
    return str(recording.get("telegram_id") or "").strip()


async def _recover_premium_download_inner(token: str, chat_id: str) -> None:
    recovery = state.setdefault("premium_recoveries", {}).setdefault(token, {})
    item = state.setdefault("recording_downloads", {}).get(token) or {}
    file_path = Path(str(item.get("file_path") or "")).resolve()
    audio_path = DOWNLOAD_ROOT / f".premium-recovery-{token[:16]}.mp3"
    transcript_path = DOWNLOAD_ROOT / f".premium-recovery-{token[:16]}.txt"
    try:
        recovery["attempts"] = int(recovery.get("attempts") or 0) + 1
        recovery["status"] = "processing"
        recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
        await save_state()

        if not bool(recovery.get("audio_delivered")):
            await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg", "-y", "-i", str(file_path),
                    "-vn", "-ac", "1", "-ar", "44100",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(audio_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await send_audio_to_recipients(
                [{"chat_id": chat_id, "caption": t(chat_id, "audio_ready_caption")}],
                audio_path,
                f"{Path(str(item.get('filename') or file_path.name)).stem}.mp3",
            )
            recovery["audio_delivered"] = True
            recovery["audio_delivered_at"] = datetime.now(timezone.utc).isoformat()
            recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
            await save_state()

        if not bool(recovery.get("transcript_delivered")):
            if not audio_path.exists():
                await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", str(file_path),
                        "-vn", "-ac", "1", "-ar", "44100",
                        "-c:a", "libmp3lame", "-b:a", "64k", str(audio_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            await tg_text(chat_id, t(chat_id, "transcribing"))
            async with TRANSCRIPTION_SEMAPHORE:
                transcript, detected_language = await asyncio.to_thread(
                    transcribe_audio_recovery_fast,
                    audio_path,
                )
            if transcript:
                transcript_path.write_text(
                    t(chat_id, "transcript_header")
                    + "\n"
                    + t(chat_id, "transcript_warning")
                    + "\n"
                    + t(chat_id, "transcript_detected", languages=detected_language)
                    + "\n\n"
                    + transcript,
                    encoding="utf-8",
                )
                with transcript_path.open("rb") as fp:
                    await telegram(
                        "sendDocument",
                        {
                            "chat_id": chat_id,
                            "caption": t(chat_id, "transcript_ready_caption"),
                        },
                        {
                            "document": (
                                f"{Path(str(item.get('filename') or file_path.name)).stem}-transcript.txt",
                                fp,
                                "text/plain",
                            )
                        },
                    )
            else:
                await tg_text(chat_id, t(chat_id, "transcript_empty"))
            recovery["transcript_delivered"] = True
            recovery["transcript_empty"] = not bool(transcript)
            recovery["transcript_delivered_at"] = datetime.now(timezone.utc).isoformat()

        recovery["status"] = "completed"
        recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
        recovery["last_error"] = ""
        await save_state()
    except Exception as exc:
        recovery["status"] = "failed"
        recovery["last_error"] = repr(exc)[:1000]
        recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
        await save_state()
        print(f"premium recovery failed for {token}: {exc!r}", flush=True)
    finally:
        audio_path.unlink(missing_ok=True)
        transcript_path.unlink(missing_ok=True)
        premium_recovery_tasks.pop(token, None)


async def premium_upgrade_backfill_loop() -> None:
    """Backfill Premium outputs when a user upgrades after a recent meeting.

    Only exact download artifacts are considered, ownership must resolve safely,
    the user must be Premium now, and the recording must have occurred outside
    any Premium entitlement window. Existing Premium meetings are never resent.
    """
    await asyncio.sleep(8)
    while True:
        try:
            downloads = list(state.setdefault("recording_downloads", {}).items())
            for token, item in downloads:
                recovery = state.setdefault("premium_recoveries", {}).get(token) or {}
                recovery_status = str(recovery.get("status") or "")
                recovery_task = premium_recovery_tasks.get(token)
                if recovery_status == "completed":
                    continue
                if recovery_status in {"queued", "processing"} and recovery_task is not None and not recovery_task.done():
                    continue
                if int(recovery.get("attempts") or 0) >= 3 and recovery_status not in {"queued", "processing"}:
                    continue

                item = item or {}
                expires_raw = str(item.get("expires_at") or "")
                try:
                    expires_at = isoparse(expires_raw)
                except Exception:
                    continue
                if datetime.now(timezone.utc) >= expires_at:
                    continue

                file_path = Path(str(item.get("file_path") or "")).resolve()
                try:
                    file_path.relative_to(DOWNLOAD_ROOT)
                except ValueError:
                    continue
                if not file_path.exists() or not file_path.is_file():
                    continue

                created_raw = str(item.get("created_at") or "").strip()
                if not created_raw:
                    ttl_hours = int(item.get("ttl_hours") or FREE_DOWNLOAD_TTL_HOURS)
                    created_raw = (
                        expires_at - timedelta(hours=ttl_hours)
                    ).isoformat()
                recording = await asyncio.to_thread(
                    find_recording_for_artifact,
                    str(item.get("filename") or file_path.name),
                    int(file_path.stat().st_size),
                    created_raw,
                    15,
                )
                if not recording:
                    continue

                chat_id = str(recording.get("telegram_id") or "").strip()
                recorded_at = str(recording.get("created_at") or "").strip()
                if not chat_id or not recorded_at:
                    continue
                if not await asyncio.to_thread(is_premium, chat_id):
                    continue
                if await asyncio.to_thread(was_premium_at, chat_id, recorded_at):
                    continue

                recovery = state.setdefault("premium_recoveries", {}).setdefault(token, {})
                recovery["chat_id"] = chat_id
                recovery["status"] = "queued"
                recovery["reason"] = "upgraded_after_recording"
                recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
                await save_state()
                task = premium_recovery_tasks.get(token)
                if task is None or task.done():
                    premium_recovery_tasks[token] = asyncio.create_task(
                        _recover_premium_download_inner(token, chat_id)
                    )
                print(
                    f"premium upgrade backfill queued token={token[:8]} chat_id={chat_id}",
                    flush=True,
                )
        except Exception as exc:
            print("premium upgrade backfill loop error:", repr(exc), flush=True)

        await asyncio.sleep(60)


@app.get("/recover-premium/{token}")
async def recover_premium_download(token: str) -> dict[str, Any]:
    item = state.setdefault("recording_downloads", {}).get(token)
    if not item:
        raise HTTPException(status_code=404, detail="Download not found or expired")
    expires_raw = str(item.get("expires_at") or "")
    try:
        expires_at = isoparse(expires_raw)
    except Exception:
        raise HTTPException(status_code=410, detail="Download expired")
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(status_code=410, detail="Download expired")

    file_path = Path(str(item.get("file_path") or "")).resolve()
    try:
        file_path.relative_to(DOWNLOAD_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="Download not found")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Download file missing")

    chat_id = await _resolve_download_owner(token, item, file_path)
    if not chat_id or not await asyncio.to_thread(is_premium, chat_id):
        raise HTTPException(status_code=409, detail="Premium is not active for recording owner")

    recovery = state.setdefault("premium_recoveries", {}).setdefault(token, {})
    if recovery.get("status") == "completed":
        return {
            "ok": True,
            "queued": False,
            "duplicate": True,
            "status": "completed",
            "audio_delivered": bool(recovery.get("audio_delivered")),
            "transcript_delivered": bool(recovery.get("transcript_delivered")),
        }

    recovery["chat_id"] = chat_id
    recovery["status"] = "queued"
    recovery["updated_at"] = datetime.now(timezone.utc).isoformat()
    await save_state()

    task = premium_recovery_tasks.get(token)
    if task is None or task.done():
        premium_recovery_tasks[token] = asyncio.create_task(
            _recover_premium_download_inner(token, chat_id)
        )
    return {"ok": True, "queued": True, "status": recovery.get("status")}


@app.get("/recover-premium/{token}/status")
async def recover_premium_download_status(token: str) -> dict[str, Any]:
    recovery = state.setdefault("premium_recoveries", {}).get(token)
    if not recovery:
        raise HTTPException(status_code=404, detail="Recovery not found")
    return {
        "ok": True,
        "status": recovery.get("status"),
        "audio_delivered": bool(recovery.get("audio_delivered")),
        "transcript_delivered": bool(recovery.get("transcript_delivered")),
        "transcript_empty": bool(recovery.get("transcript_empty")),
        "last_error": str(recovery.get("last_error") or ""),
        "updated_at": recovery.get("updated_at"),
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    remote_free_slots = sum(
        int(entry.get("slots") or 0)
        for entry in remote_worker_cache.values()
        if _remote_worker_alive(entry) and entry.get("pool") == "free"
    )
    remote_premium_slots = sum(
        int(entry.get("slots") or 0)
        for entry in remote_worker_cache.values()
        if _remote_worker_alive(entry) and entry.get("pool") == "premium"
    )
    remote_free_available_slots = sum(
        int(entry.get("available_slots") or 0)
        for entry in remote_worker_cache.values()
        if _remote_worker_alive(entry) and entry.get("pool") == "free"
    )
    remote_premium_available_slots = sum(
        int(entry.get("available_slots") or 0)
        for entry in remote_worker_cache.values()
        if _remote_worker_alive(entry) and entry.get("pool") == "premium"
    )
    total_free_slots = FREE_MEETING_SLOTS + remote_free_slots
    total_premium_slots = PREMIUM_MEETING_SLOTS + remote_premium_slots
    recorder_profiles = profile_status()
    active_account_ids = sorted({
        str(entry.get("account_id") or "primary")
        for entry in remote_worker_cache.values()
        if _remote_worker_alive(entry)
    })
    return {
        "ok": True,
        "calendar_connected": TOKEN_FILE.exists(),
        "personal_calendar_connections": len(list(USER_TOKEN_DIR.glob("*.json"))),
        "auto_join_users": sum(1 for enabled in state.get("auto_join_all", {}).values() if enabled),
        "bot_email": BOT_EMAIL,
        "admin_recipient_configured": bool(ADMINUSER),
        "max_concurrent_meetings": total_free_slots + total_premium_slots,
        "free_meeting_slots": total_free_slots,
        "premium_reserved_slots": total_premium_slots,
        "local_free_meeting_slots": FREE_MEETING_SLOTS,
        "local_premium_reserved_slots": PREMIUM_MEETING_SLOTS,
        "free_worker_endpoints": len(FREE_WORKER_URLS),
        "premium_worker_endpoints": len(PREMIUM_WORKER_URLS),
        "redis_state": STATE_STORE.ping(),
        "database_backend": "postgresql" if is_postgres() else "sqlite",
        "healthy_free_workers": sum(1 for url in FREE_WORKER_URLS if worker_health_cache.get(url, True)),
        "healthy_premium_workers": sum(1 for url in PREMIUM_WORKER_URLS if worker_health_cache.get(url, True)),
        "free_queue": sum(1 for item in state.get("join_queue", []) if not bool(item.get("premium"))),
        "premium_queue": sum(1 for item in state.get("join_queue", []) if bool(item.get("premium"))),
        "transcription_concurrency": int(os.environ.get("TRANSCRIPTION_CONCURRENCY", "1")),
        "active_delivery_jobs": int(active_delivery_jobs),
        "pending_delivery_jobs": len(state.get("pending_deliveries", {})),
        "delivery_pipeline_busy": bool(active_delivery_jobs or state.get("pending_deliveries")),
        "remote_workers": sum(1 for entry in remote_worker_cache.values() if _remote_worker_alive(entry)),
        "remote_free_slots": remote_free_slots,
        "remote_premium_slots": remote_premium_slots,
        "remote_free_available_slots": remote_free_available_slots,
        "remote_premium_available_slots": remote_premium_available_slots,
        "autoscaler_enabled": autoscaler_enabled(),
        "recorder_account_profiles": int(recorder_profiles.get("count") or 0),
        "recorder_account_ids": recorder_profiles.get("ids") or [],
        "active_remote_account_ids": active_account_ids,
    }


PUBLIC_SITE_CSS = """
:root{color-scheme:dark;--bg:#07110f;--panel:#0d1c18;--text:#f4fbf8;--muted:#a9bbb5;--line:#1e3730;--accent:#65e6b5;--accent2:#8ca8ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#12352b 0,transparent 34rem),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.6}
a{color:inherit}.wrap{width:min(1120px,calc(100% - 40px));margin:auto}.nav{display:flex;align-items:center;justify-content:space-between;padding:26px 0}.brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.02em;text-decoration:none}.mark{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(145deg,var(--accent),var(--accent2));color:#06110e;font-weight:900}.links{display:flex;gap:22px;color:var(--muted);font-size:14px}.links a{text-decoration:none}.hero{padding:88px 0 58px}.eyebrow{display:inline-flex;padding:7px 12px;border:1px solid var(--line);border-radius:999px;color:var(--accent);background:#0a1714;font-size:13px}.hero h1{max-width:820px;font-size:clamp(44px,7vw,82px);line-height:1.02;letter-spacing:-.055em;margin:24px 0}.hero p{max-width:720px;font-size:20px;color:var(--muted);margin:0}.cta{margin-top:34px;display:flex;flex-wrap:wrap;gap:12px}.button{display:inline-flex;padding:13px 18px;border-radius:12px;text-decoration:none;font-weight:750;background:var(--accent);color:#05110d}.button.secondary{background:transparent;color:var(--text);border:1px solid var(--line)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:28px 0 80px}.card{padding:24px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(180deg,#0d1d19,#091512)}.card b{display:block;margin-bottom:8px;font-size:17px}.card p{margin:0;color:var(--muted)}.section{padding:70px 0;border-top:1px solid var(--line)}.section h2{font-size:34px;letter-spacing:-.035em;margin:0 0 14px}.section>div>p{max-width:760px;color:var(--muted)}.data{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:28px}.notice{padding:22px;border-radius:18px;background:#0a1714;border:1px solid var(--line);color:var(--muted)}.notice strong{color:var(--text)}.legal{max-width:820px;padding:60px 0 100px}.legal h1{font-size:48px;letter-spacing:-.04em;line-height:1.1}.legal h2{margin-top:38px;font-size:24px}.legal p,.legal li{color:var(--muted)}.legal a{color:var(--accent)}footer{border-top:1px solid var(--line);padding:30px 0 42px;color:var(--muted);font-size:14px}.foot{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.foot a{margin-left:18px;text-decoration:none}
@media(max-width:760px){.links{display:none}.hero{padding-top:56px}.grid,.data{grid-template-columns:1fr}.hero p{font-size:18px}.legal h1{font-size:38px}}
"""

def public_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="BeOnMeet automatically joins scheduled Google Meet meetings, records them, and delivers the result to Telegram.">
<style>{PUBLIC_SITE_CSS}</style></head>
<body><div class="wrap"><nav class="nav"><a class="brand" href="/"><span class="mark">B</span>BeOnMeet</a>
<div class="links"><a href="/#how">How it works</a><a href="/#data">Google data</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a></div></nav></div>
{body}
<footer><div class="wrap foot"><span>© 2026 BeOnMeet</span><span><a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a></span></div></footer>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    body = """
<main>
<section class="hero"><div class="wrap">
<span class="eyebrow">Automatic Google Meet recorder for Telegram</span>
<h1>Your calendar knows the meeting. BeOnMeet handles the rest.</h1>
<p>Connect Google Calendar once. BeOnMeet detects scheduled Google Meet events across your accessible calendars, joins at meeting time, records the session and delivers the result to your Telegram chat.</p>
<div class="cta"><a class="button" href="#how">See how it works</a><a class="button secondary" href="/privacy">How Google data is used</a></div>
</div></section>
<section id="how"><div class="wrap grid">
<div class="card"><b>1. Connect once with Premium</b><p>Premium users authorize read only access to Google Calendar from the BeOnMeet Telegram bot.</p></div>
<div class="card"><b>2. Meetings are detected</b><p>Google Meet events are found automatically whether you organize them or are invited to them. Cancelled and declined events are ignored.</p></div>
<div class="card"><b>3. Receive the result</b><p>The recorder joins at the scheduled time and sends the recording back to the Telegram user who connected the calendar.</p></div>
</div></section>
<section class="section" id="data"><div class="wrap">
<h2>Designed around minimum Google access</h2>
<p>BeOnMeet requests read only Calendar permissions. It does not create, edit or delete your Google Calendar events.</p>
<div class="data">
<div class="notice"><strong>Calendar list</strong><br>Used to discover the calendars available to your Google account so meetings are not limited to the primary calendar.</div>
<div class="notice"><strong>Calendar events</strong><br>Used to identify Google Meet links, event timing and whether an event is cancelled or declined so the recorder can join at the correct time.</div>
</div>
<div class="notice" style="margin-top:16px"><strong>No advertising use of Google user data.</strong><br>Google user data obtained through Google APIs is used only to provide BeOnMeet's user facing meeting automation. It is not sold and is not used for advertising or ad targeting. See the <a href="/privacy">Privacy Policy</a> for full details.</div>
</div></section>
<section class="section"><div class="wrap">
<h2>Recordings delivered where you already work</h2>
<p>Meeting recordings and eligible Premium outputs such as separate audio and transcripts are delivered through Telegram. Temporary delivery files are retained only as needed to complete delivery and, depending on plan, may remain available for up to 72 hours before expiry.</p>
</div></section>
</main>"""
    return public_shell("BeOnMeet | Automatic Google Meet recording", body)


@app.get("/privacy", response_class=HTMLResponse)
@app.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    body = """
<main><div class="wrap legal">
<span class="eyebrow">Effective 6 October 2026</span>
<h1>BeOnMeet Privacy Policy</h1>
<p>This policy explains how BeOnMeet accesses, uses, stores and shares information when you use the BeOnMeet meeting automation service.</p>
<h2>Information we process</h2>
<p>When you connect Google Calendar, BeOnMeet receives OAuth authorization and read only access to the calendars and events available to the connected Google account. This can include calendar identifiers, event timing, Google Meet links, event status and attendee response information needed to determine whether a meeting should be joined.</p>
<p>We also process Telegram account identifiers required to deliver bot messages and files, service and payment status, operational logs, and meeting media created when you ask BeOnMeet to record a meeting.</p>
<h2>How Google user data is used</h2>
<p>Google Calendar data is used only to provide user facing BeOnMeet functionality: discovering scheduled Google Meet meetings, determining when the recorder should join, avoiding cancelled or declined meetings, preventing duplicate recorder joins, and associating meeting automation with the Telegram user who connected the Google account.</p>
<p>BeOnMeet requests read only Google Calendar scopes. BeOnMeet does not use these permissions to create, modify or delete your Google Calendar events.</p>
<h2>Google API Limited Use</h2>
<p>BeOnMeet's use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements. Google user data is not sold, is not used for advertising or ad targeting, and is not transferred to third parties for advertising purposes.</p>
<h2>Storage and retention</h2>
<p>OAuth credentials required to keep your calendar connection active are stored on BeOnMeet infrastructure with access restricted to the service. Minimal scheduling state may be retained so that meetings can be queued, deduplicated and delivered reliably.</p>
<p>Meeting recordings and derived files are processed for delivery to the requesting Telegram user. Temporary delivery files expire after the applicable delivery window. Depending on the plan and output type, a full file download can remain available for up to 72 hours before expiry.</p>
<h2>Sharing</h2>
<p>We disclose data only as necessary to operate the service, including communication with Google APIs for Calendar access and Telegram for bot communication and file delivery, or when required by law. We do not sell personal information.</p>
<h2>Your choices and deletion</h2>
<p>You can turn off automatic meeting detection in the BeOnMeet bot and revoke BeOnMeet's Google access at any time from your Google Account permissions. Revoking Google access prevents future Calendar reads. To request deletion of BeOnMeet account data that remains on the service, contact <a href="mailto:meetrecorderbot@gmail.com">meetrecorderbot@gmail.com</a>.</p>
<h2>Recording responsibility</h2>
<p>Meeting recording can be regulated by local law or organizational policy. The user who requests or enables recording is responsible for obtaining any required notice or consent from meeting participants.</p>
<h2>Security</h2>
<p>We use access controls, isolated service components and operational safeguards intended to protect credentials and meeting data. No internet service can guarantee absolute security.</p>
<h2>Changes</h2>
<p>If our use of Google user data or other material privacy practices change, this policy will be updated before the new use is introduced where required.</p>
<h2>Contact</h2>
<p>Privacy questions and deletion requests: <a href="mailto:meetrecorderbot@gmail.com">meetrecorderbot@gmail.com</a>.</p>
</div></main>"""
    return public_shell("Privacy Policy | BeOnMeet", body)


@app.get("/terms", response_class=HTMLResponse)
@app.get("/terms-of-service", response_class=HTMLResponse)
async def terms_of_service() -> str:
    body = """
<main><div class="wrap legal">
<span class="eyebrow">Effective 6 October 2026</span>
<h1>BeOnMeet Terms of Service</h1>
<p>These Terms govern use of BeOnMeet. By connecting an account or requesting a recording, you agree to these Terms.</p>
<h2>Service</h2>
<p>BeOnMeet is a meeting automation service that can detect eligible Google Meet events from a connected Google Calendar, dispatch a recorder, and deliver recording related outputs through Telegram. Features and capacity can vary by plan.</p>
<h2>Your responsibilities</h2>
<ul><li>You must have the right to connect the Google account you authorize.</li><li>You are responsible for complying with meeting, workplace and local laws, including any notice or consent required before recording participants.</li><li>You may not use BeOnMeet for unlawful surveillance, harassment, unauthorized access or other illegal activity.</li></ul>
<h2>Google and Telegram</h2>
<p>Google Meet, Google Calendar and Telegram are third party services. BeOnMeet is not affiliated with or endorsed by Google or Telegram. Their availability and policies can affect BeOnMeet functionality.</p>
<h2>Availability</h2>
<p>We work to provide reliable automatic joining and delivery, but admission controls, network conditions, third party outages, capacity limits or meeting configuration can prevent or delay recording. A host may need to admit the recorder.</p>
<h2>Plans and temporary files</h2>
<p>Free and Premium plans can have different recording limits, quality, output and retention features. Temporary delivery and download files expire according to the applicable plan and service configuration.</p>
<h2>Privacy</h2>
<p>Our handling of personal information and Google user data is described in the <a href="/privacy">Privacy Policy</a>.</p>
<h2>Suspension</h2>
<p>We may restrict access when reasonably necessary to protect the service, other users or third parties, or to address fraud, abuse or legal requirements.</p>
<h2>Disclaimer</h2>
<p>BeOnMeet is provided on an as available basis. To the maximum extent permitted by law, we do not guarantee that every meeting will be joined, recorded, transcribed or delivered without interruption or error.</p>
<h2>Contact</h2>
<p>Questions about these Terms: <a href="mailto:meetrecorderbot@gmail.com">meetrecorderbot@gmail.com</a>.</p>
</div></main>"""
    return public_shell("Terms of Service | BeOnMeet", body)


@app.get("/auth/google")
async def auth_google(chat_id: str | None = None) -> RedirectResponse:
    normalized_chat_id = None
    if chat_id:
        try:
            normalized_chat_id = _safe_chat_id(chat_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Telegram chat id")

    if normalized_chat_id and not await asyncio.to_thread(is_premium, normalized_chat_id):
        raise HTTPException(status_code=403, detail="Premium required for All meetings")

    flow = google_flow(
        scopes=PERSONAL_SCOPES if normalized_chat_id else LEGACY_SCOPES,
    )
    authorization_url, oauth_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if normalized_chat_id:
        state.setdefault("oauth_states", {})[oauth_state] = {
            "chat_id": normalized_chat_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        state["oauth_state"] = oauth_state
    await save_state()
    return RedirectResponse(authorization_url)


@app.get("/auth/google/callback", response_class=HTMLResponse)
async def auth_google_callback(request: Request, state: str) -> str:
    oauth_entry = globals()["state"].setdefault("oauth_states", {}).pop(state, None)
    legacy_flow = state == globals()["state"].get("oauth_state")
    if not oauth_entry and not legacy_flow:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    oauth_chat_id = str((oauth_entry or {}).get("chat_id") or "")
    if oauth_chat_id and not await asyncio.to_thread(is_premium, oauth_chat_id):
        raise HTTPException(status_code=403, detail="Premium required for All meetings")

    flow = google_flow(
        state,
        scopes=PERSONAL_SCOPES if oauth_entry else LEGACY_SCOPES,
    )
    callback_url = f"https://{DOMAIN}/auth/google/callback?{request.url.query}"
    flow.fetch_token(authorization_response=callback_url)
    creds = flow.credentials

    chat_id = oauth_chat_id
    if chat_id:
        google_token_file(chat_id).write_text(creds.to_json())
        globals()["state"].setdefault("auto_join_all", {})[chat_id] = True
        await save_state()
        try:
            await tg_text(chat_id, t(chat_id, "auto_enabled"), with_menu=True)
        except Exception as exc:
            print("calendar connect Telegram confirmation error:", repr(exc), flush=True)
        return (
            "<h2>Google Calendar connected ✅</h2>"
            "<p>Automatic mode is on. BeOnMeet will now detect Google Meet events "
            "across all calendars in this Google account automatically. You can close this page.</p>"
        )

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
        await tg_text(chat_id, t(chat_id, "waiting_admission"))
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
        await tg_text(chat_id, t(chat_id, "recording_started"))
    return {"ok": True}


async def _process_recording_inner(data: dict[str, Any], raw_path: Path) -> dict[str, Any]:
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
            "caption": t(chat_id, "recording_ready_caption"),
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
            # Large recordings are already transcoded into Telegram-safe MP4 parts
            # by send_recording_to_recipients(). Avoid a wasteful full-file encode
            # followed by a second segmented encode.
            if raw_path.stat().st_size <= 49 * 1024 * 1024:
                free_path = raw_path.with_name(f"{raw_path.stem}_standard.mp4")
                await asyncio.to_thread(
                    subprocess.run,
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

        pending_id = str(data.get("_pending_id") or "")
        pending_state = state.setdefault("pending_deliveries", {}).get(pending_id) if pending_id else None
        video_already_delivered = bool((pending_state or {}).get("video_delivered"))

        if not video_already_delivered:
            await tg_text(chat_id, t(chat_id, "recording_finished"))
            await send_recording_to_recipients(recipients, delivery_path, delivery_filename)
            if pending_state is not None:
                pending_state["video_delivered"] = True
                pending_state["video_delivered_at"] = datetime.now(timezone.utc).isoformat()
                pending_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                await save_state()
        await asyncio.to_thread(
            record_recording,
            chat_id,
            meeting_link,
            delivery_filename,
            int(delivery_path.stat().st_size),
            int(data.get("duration") or 0),
        )

        if premium_active:
            audio_already_delivered = bool((pending_state or {}).get("audio_delivered"))
            transcript_already_delivered = bool((pending_state or {}).get("transcript_delivered"))
            audio_delivery_error: Exception | None = None
            transcript_processing_error: Exception | None = None

            if not (audio_already_delivered and transcript_already_delivered):
                audio_path = raw_path.with_suffix(".mp3")
                try:
                    # Speech-friendly mono audio keeps most meetings under Telegram's
                    # 50 MB Bot API upload cap. Very long meetings transparently fall
                    # back to the secure expiring download link.
                    await asyncio.to_thread(
                        subprocess.run,
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(raw_path),
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            "44100",
                            "-c:a",
                            "libmp3lame",
                            "-b:a",
                            "64k",
                            str(audio_path),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                    if not audio_already_delivered:
                        try:
                            await send_audio_to_recipients(
                                [{
                                    "chat_id": chat_id,
                                    "caption": t(chat_id, "audio_ready_caption"),
                                }],
                                audio_path,
                                f"{Path(filename).stem}.mp3",
                            )
                            if pending_state is not None:
                                pending_state["audio_delivered"] = True
                                pending_state["audio_delivered_at"] = datetime.now(timezone.utc).isoformat()
                                pending_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                                await save_state()
                            audio_already_delivered = True
                        except Exception as exc:
                            audio_delivery_error = exc
                            print("audio delivery error:", repr(exc), flush=True)

                        # Admin copy is best effort and must never cause a duplicate
                        # user delivery or block transcript generation.
                        if audio_already_delivered and ADMINUSER and ADMINUSER != chat_id:
                            try:
                                await send_audio_to_recipients(
                                    [{
                                        "chat_id": ADMINUSER,
                                        "caption": (
                                            "🎧 فایل صوتی نسخه ویژه\n\n"
                                            f"👤 درخواست دهنده:\n{who}\n"
                                            f"🔗 جلسه: {meeting_link or 'نامشخص'}"
                                        ),
                                    }],
                                    audio_path,
                                    f"{Path(filename).stem}.mp3",
                                )
                            except Exception as exc:
                                print("admin audio copy error:", repr(exc), flush=True)

                    if not transcript_already_delivered:
                        try:
                            await tg_text(chat_id, t(chat_id, "transcribing"))
                            async with TRANSCRIPTION_SEMAPHORE:
                                try:
                                    transcript, detected_language = await asyncio.to_thread(
                                        transcribe_audio_local,
                                        audio_path,
                                    )
                                except Exception as primary_transcription_error:
                                    # large-v3 can fail under CPU/RAM pressure or on a
                                    # damaged tail in an abruptly ended WebM. Retry once
                                    # with the smaller recovery model before surfacing an
                                    # error to the user or leaving the stage pending.
                                    print(
                                        "primary transcription failed; trying recovery model:",
                                        repr(primary_transcription_error),
                                        flush=True,
                                    )
                                    transcript, detected_language = await asyncio.to_thread(
                                        transcribe_audio_recovery_fast,
                                        audio_path,
                                    )

                            if transcript:
                                transcript_path = raw_path.with_name(
                                    f"{raw_path.stem}_transcript.txt"
                                )
                                try:
                                    transcript_path.write_text(
                                        t(chat_id, "transcript_header")
                                        + "\n"
                                        + t(chat_id, "transcript_warning")
                                        + "\n"
                                        + t(
                                            chat_id,
                                            "transcript_detected",
                                            languages=detected_language,
                                        )
                                        + "\n\n"
                                        + transcript,
                                        encoding="utf-8",
                                    )
                                    with transcript_path.open("rb") as fp:
                                        await telegram(
                                            "sendDocument",
                                            {
                                                "chat_id": chat_id,
                                                "caption": t(chat_id, "transcript_ready_caption"),
                                            },
                                            {
                                                "document": (
                                                    f"{Path(filename).stem}-transcript.txt",
                                                    fp,
                                                    "text/plain",
                                                )
                                            },
                                        )

                                    if pending_state is not None:
                                        pending_state["transcript_delivered"] = True
                                        pending_state["transcript_delivered_at"] = datetime.now(timezone.utc).isoformat()
                                        pending_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                                        await save_state()
                                    transcript_already_delivered = True

                                    if ADMINUSER and ADMINUSER != chat_id:
                                        try:
                                            with transcript_path.open("rb") as fp:
                                                await telegram(
                                                    "sendDocument",
                                                    {
                                                        "chat_id": ADMINUSER,
                                                        "caption": (
                                                            "📝 متن جلسه نسخه ویژه\n\n"
                                                            f"👤 درخواست دهنده:\n{who}\n"
                                                            f"🔗 جلسه: {meeting_link or 'نامشخص'}"
                                                        ),
                                                    },
                                                    {
                                                        "document": (
                                                            f"{Path(filename).stem}-transcript.txt",
                                                            fp,
                                                            "text/plain",
                                                        )
                                                    },
                                                )
                                        except Exception as exc:
                                            print("admin transcript copy error:", repr(exc), flush=True)
                                finally:
                                    transcript_path.unlink(missing_ok=True)
                            else:
                                await tg_text(chat_id, t(chat_id, "transcript_empty"))
                                if pending_state is not None:
                                    pending_state["transcript_delivered"] = True
                                    pending_state["transcript_empty"] = True
                                    pending_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                                    await save_state()
                                transcript_already_delivered = True
                        except Exception as exc:
                            transcript_processing_error = exc
                            print("transcription error:", repr(exc), flush=True)
                            if not bool(data.get("_silent_retry")):
                                try:
                                    await tg_text(chat_id, t(chat_id, "transcript_error"))
                                except Exception as notify_exc:
                                    print("transcript error notification failed:", repr(notify_exc), flush=True)
                finally:
                    audio_path.unlink(missing_ok=True)

            # Never delete the source recording while a Premium deliverable is
            # incomplete. Recovery retries only the missing stage because the
            # per-stage flags above are persisted in Redis state.
            if audio_delivery_error is not None or transcript_processing_error is not None:
                raise RuntimeError(
                    "premium downstream delivery incomplete: "
                    f"audio={audio_delivery_error!r} transcript={transcript_processing_error!r}"
                )

        if free_path:
            free_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)

        completed_event_id = str(data.get("botId") or data.get("eventId") or "").strip()
        if completed_event_id:
            state.setdefault("launched_events", {}).pop(completed_event_id, None)
            await save_state()

        return {"ok": True, "admin_copy": bool(ADMINUSER), "premium": premium_active}
    except Exception as exc:
        # Do not tell the user that Telegram delivery failed when the recording
        # itself was already delivered successfully. Premium audio/transcript
        # stages have their own error handling and are retried from the retained
        # source by delivery_recovery_loop().
        pending_id_after_failure = str(data.get("_pending_id") or "")
        pending_after_failure = (
            state.setdefault("pending_deliveries", {}).get(pending_id_after_failure)
            if pending_id_after_failure
            else None
        )
        video_delivered_after_failure = bool(
            (pending_after_failure or {}).get("video_delivered")
        )
        if not bool(data.get("_silent_retry")) and not video_delivered_after_failure:
            await tg_text(chat_id, t(chat_id, "delivery_error"))
        elif video_delivered_after_failure:
            print(
                "recording delivered; downstream Premium output remains pending:",
                repr(exc),
                flush=True,
            )
        raise HTTPException(status_code=502, detail=str(exc))


async def _process_recording_locked(data: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    global active_delivery_jobs

    chat_id = str(data.get("userId") or "").strip()
    event_id = str(data.get("botId") or data.get("eventId") or "").strip()
    pending_id = event_id or f"{chat_id}:{raw_path.name}"
    pending = state.setdefault("pending_deliveries", {}).get(pending_id) or {}
    attempts = int(pending.get("attempts") or 0) + 1
    state["pending_deliveries"][pending_id] = {
        **pending,
        "event_id": event_id,
        "chat_id": chat_id,
        "file_path": str(raw_path),
        "source_name": raw_path.name,
        "filename": str(data.get("filename") or raw_path.name),
        "meeting_link": str(data.get("meetingLink") or ""),
        "duration": int(data.get("duration") or 0),
        "attempts": attempts,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_error": "",
    }
    if event_id:
        launched = state.setdefault("launched_events", {}).setdefault(event_id, {})
        launched["status"] = "delivering"
        launched["delivery_started_at"] = datetime.now(timezone.utc).isoformat()
    await save_state()

    active_delivery_jobs += 1
    try:
        data = {**data, "_pending_id": pending_id}
        result = await _process_recording_inner(data, raw_path)
        state.setdefault("pending_deliveries", {}).pop(pending_id, None)
        await save_state()
        return result
    except Exception as exc:
        current = state.setdefault("pending_deliveries", {}).get(pending_id)
        if current is not None:
            current["last_error"] = repr(exc)[:1000]
            current["updated_at"] = datetime.now(timezone.utc).isoformat()
            await save_state()
        raise
    finally:
        active_delivery_jobs = max(0, active_delivery_jobs - 1)


async def _process_recording(data: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    """Serialize delivery per meeting so endpoint retries and recovery cannot race."""
    chat_id = str(data.get("userId") or "").strip()
    event_id = str(data.get("botId") or data.get("eventId") or "").strip()
    pending_id = event_id or f"{chat_id}:{raw_path.name}"
    lock = delivery_locks.setdefault(pending_id, asyncio.Lock())

    async with lock:
        # A duplicate retry can arrive after the first delivery already completed
        # and removed the source file. Treat it as idempotent success.
        if not raw_path.exists() and pending_id not in state.setdefault("pending_deliveries", {}):
            return {"ok": True, "duplicate": True, "pending_id": pending_id}
        return await _process_recording_locked(data, raw_path)



async def delivery_recovery_loop() -> None:
    await asyncio.sleep(5)

    # Pending deliveries are retried by the generic idempotent loop below.
    # Per-meeting locks prevent endpoint/recovery races and per-stage flags
    # resume only the missing Premium deliverables.

    while True:
        try:
            if active_delivery_jobs:
                await asyncio.sleep(15)
                continue

            pending_items = list(state.setdefault("pending_deliveries", {}).items())
            if not pending_items:
                # Never infer a meeting from arbitrary files on disk. Recovery is
                # allowed only from an exact pending-delivery record that carries
                # the original event id and exact recorder file path.
                await asyncio.sleep(30)
                continue

            for pending_id, pending in pending_items:
                if active_delivery_jobs:
                    break

                pending = pending or {}
                attempts = int(pending.get("attempts") or 0)
                if attempts >= 8:
                    continue

                event_id_for_retry = str(pending.get("event_id") or "").strip()
                chat_id_for_retry = str(pending.get("chat_id") or "").strip()
                stored_file_path = str(pending.get("file_path") or "").strip()
                if not event_id_for_retry or not chat_id_for_retry or not stored_file_path:
                    print(
                        f"dropping unsafe pending delivery {pending_id}: "
                        "missing exact event/chat/file identity",
                        flush=True,
                    )
                    state.setdefault("pending_deliveries", {}).pop(pending_id, None)
                    await save_state()
                    continue

                # The pending key must be the exact event id. This prevents an old
                # retained file from being associated with a later meeting by user id.
                if str(pending_id) != event_id_for_retry:
                    print(
                        f"dropping unsafe pending delivery {pending_id}: "
                        f"event mismatch {event_id_for_retry}",
                        flush=True,
                    )
                    state.setdefault("pending_deliveries", {}).pop(pending_id, None)
                    await save_state()
                    continue

                raw_path = Path(stored_file_path).resolve()
                try:
                    raw_path.relative_to(RECORDING_ROOT)
                except ValueError:
                    print(
                        f"dropping unsafe pending delivery {pending_id}: "
                        "file is outside recording root",
                        flush=True,
                    )
                    state.setdefault("pending_deliveries", {}).pop(pending_id, None)
                    await save_state()
                    continue
                if not raw_path.exists() or not raw_path.is_file():
                    state.setdefault("pending_deliveries", {}).pop(pending_id, None)
                    missing_event_id = str((pending or {}).get("event_id") or "")
                    if missing_event_id:
                        launched = state.setdefault("launched_events", {}).get(missing_event_id) or {}
                        if str(launched.get("status") or "") == "delivering":
                            state["launched_events"].pop(missing_event_id, None)
                    await save_state()
                    print(f"dropped stale pending delivery {pending_id}: source file is gone", flush=True)
                    continue
                updated_raw = str((pending or {}).get("updated_at") or "")
                try:
                    updated = isoparse(updated_raw) if updated_raw else datetime.now(timezone.utc) - timedelta(minutes=10)
                except Exception:
                    updated = datetime.now(timezone.utc) - timedelta(minutes=10)
                if datetime.now(timezone.utc) - updated < timedelta(seconds=30):
                    continue

                recovery_data = {
                    "userId": str((pending or {}).get("chat_id") or ""),
                    "eventId": str((pending or {}).get("event_id") or ""),
                    "botId": str((pending or {}).get("event_id") or ""),
                    "meetingLink": str((pending or {}).get("meeting_link") or ""),
                    "filename": str((pending or {}).get("filename") or raw_path.name),
                    "duration": int((pending or {}).get("duration") or 0),
                    "_silent_retry": True,
                }
                print(f"retrying pending delivery {pending_id} attempt={attempts + 1}", flush=True)
                try:
                    await _process_recording(recovery_data, raw_path)
                except Exception as exc:
                    print("pending delivery recovery error:", repr(exc), flush=True)
        except Exception as exc:
            print("delivery recovery loop error:", repr(exc), flush=True)

        await asyncio.sleep(30)


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
