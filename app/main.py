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
app.include_router(autoscaler_router)

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
queue_mutation_lock = asyncio.Lock()
worker_health_cache: dict[str, bool] = {}
remote_worker_cache: dict[str, dict[str, Any]] = {}
_whisper_model = None
state: dict[str, Any] = {
    "telegram_offset": 0,
    "requests": {},
    "launched_events": {},
    "join_queue": [],
    "remote_claims": {},
    "oauth_state": None,
    "user_languages": {},
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
    state.setdefault("user_languages", {})
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
        [{"text": labels["now"]}, {"text": labels["help"]}],
        [{"text": labels["language"]}],
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
                {"command": "language", "description": profile["commands"]["language"]},
            ]
            await telegram("setMyCommands", {
                "scope": json.dumps({"type": "all_private_chats"}),
                "language_code": lang,
                "commands": json.dumps(public_commands, ensure_ascii=False),
            })

        # English is the neutral default when Telegram does not provide a language.
        default_profile = i18n_profile("en")
        default_commands = [
            {"command": "start", "description": default_profile["commands"]["start"]},
            {"command": "plans", "description": default_profile["commands"]["plans"]},
            {"command": "now", "description": default_profile["commands"]["now"]},
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

            if changed:
                await save_state()
        except Exception as exc:
            print("state cleanup loop error:", repr(exc), flush=True)

        await asyncio.sleep(600)


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
                        intents = {}
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
                                "text": t(chat_id, "premium_offer"),
                                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                            },
                        )
                    continue

                if text.startswith("/start"):
                    if TOKEN_FILE.exists():
                        auth_status = t(chat_id, "calendar_connected")
                    else:
                        auth_status = t(
                            chat_id,
                            "calendar_disconnected",
                            url=f"https://{DOMAIN}/auth/google",
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
                    state.setdefault("pending_now", {})[str(chat_id)] = True
                    await save_state()
                    await tg_text(chat_id, t(chat_id, "now_prompt"), with_menu=True)
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
        await tg_text(
            target["chat_id"],
            t(target["chat_id"], "large_video", count=len(parts)),
        )
        for idx, part in enumerate(parts, 1):
            caption = (
                f"{target['caption']}\n\n"
                + t(target["chat_id"], "video_part", index=idx, count=len(parts))
            )
            await send_one_file(target, part, part.name, caption, "video/mp4")
    for part in parts:
        part.unlink(missing_ok=True)


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

        await tg_text(chat_id, t(chat_id, "recording_finished"))
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
                    {"chat_id": chat_id, "caption": t(chat_id, "audio_ready_caption")}
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
                    await tg_text(chat_id, t(chat_id, "transcribing"))
                    async with TRANSCRIPTION_SEMAPHORE:
                        transcript, detected_language = await asyncio.to_thread(transcribe_audio_local, audio_path)
                    if transcript:
                        transcript_path = raw_path.with_name(f"{raw_path.stem}_transcript.txt")
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
                        transcript_targets = [
                            {"chat_id": chat_id, "caption": t(chat_id, "transcript_ready_caption")}
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
                        await tg_text(chat_id, t(chat_id, "transcript_empty"))
                except Exception as transcript_error:
                    print("transcription error:", repr(transcript_error), flush=True)
                    await tg_text(chat_id, t(chat_id, "transcript_error"))
            finally:
                audio_path.unlink(missing_ok=True)

        if free_path:
            free_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)

        completed_event_id = str(data.get("botId") or data.get("eventId") or "").strip()
        if completed_event_id:
            state.setdefault("launched_events", {}).pop(completed_event_id, None)
            await save_state()

        return {"ok": True, "admin_copy": bool(ADMINUSER), "premium": premium_active}
    except Exception as exc:
        await tg_text(chat_id, t(chat_id, "delivery_error"))
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
