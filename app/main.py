import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from dateutil.parser import isoparse
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

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

BOT_EMAIL = os.environ.get("BOT_EMAIL", "meetrecorderbot@gmail.com")
DOMAIN = os.environ.get("DOMAIN", "beonmeet.smarbiz.sbs")
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", f"https://{DOMAIN}/auth/google/callback")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMINUSER = os.environ.get("ADMINUSER", "").strip()
TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
MEETING_BOT_URL = os.environ.get("MEETING_BOT_URL", "http://meeting-bot:3000").rstrip("/")
INTERNAL_SECRET = os.environ["INTERNAL_SECRET"]
RECORDING_ROOT = Path(os.environ.get("RECORDING_TMP_DIR", "/recordings")).resolve()
BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "BeOnMeet Recorder")
CALENDAR_POLL_SECONDS = int(os.environ.get("CALENDAR_POLL_SECONDS", "30"))
PAYMENT_STATUS_URL = os.environ.get(
    "PAYMENT_STATUS_URL",
    "https://pay.hamooncloud.ir/payments/beonmeet/status",
)

MEET_RE = re.compile(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:\?[^\s]*)?", re.I)
SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

state_lock = asyncio.Lock()
state: dict[str, Any] = {
    "telegram_offset": 0,
    "requests": {},
    "launched_events": {},
    "oauth_state": None,
}


def load_state() -> None:
    global state
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text())
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass


def save_state_sync() -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(STATE_FILE)


async def save_state() -> None:
    async with state_lock:
        await asyncio.to_thread(save_state_sync)


def normalize_meet_url(url: str) -> str:
    match = MEET_RE.search(url or "")
    if not match:
        return ""
    raw = match.group(0).split("?")[0].lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\\.", "", raw)
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


async def tg_text(chat_id: int | str, text: str) -> None:
    await telegram("sendMessage", {"chat_id": str(chat_id), "text": text, "disable_web_page_preview": "true"})


async def setup_telegram_profile() -> None:
    try:
        await telegram("setMyDescription", {
            "description": "لینک Google Meet رو بفرست. سر وقت وارد جلسه می‌شم، ضبطش می‌کنم و آخرش فایل رو همینجا برات می‌فرستم."
        })
        await telegram("setMyShortDescription", {
            "short_description": "ضبط خودکار Google Meet و ارسال مستقیم توی تلگرام"
        })
        public_commands = [
            {"command": "start", "description": "شروع و راهنما"},
            {"command": "plans", "description": "پلن ویژه و قیمت ها"},
            {"command": "now", "description": "ورود فوری به یک Meet در حال اجرا"},
        ]
        await telegram("setMyCommands", {
            "commands": json.dumps(public_commands, ensure_ascii=False)
        })
        if ADMINUSER:
            await telegram("setMyCommands", {
                "scope": json.dumps({"type": "chat", "chat_id": int(ADMINUSER)}),
                "commands": json.dumps(public_commands + [
                    {"command": "admin", "description": "پنل مدیریت"}
                ], ensure_ascii=False)
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
    return result.get("items", [])


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


def event_start(event: dict[str, Any]) -> datetime | None:
    value = event.get("start", {}).get("dateTime")
    if not value:
        return None
    dt = isoparse(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_end(event: dict[str, Any]) -> datetime | None:
    value = event.get("end", {}).get("dateTime")
    if not value:
        return None
    dt = isoparse(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_calendar_event_for_meet(meet_url: str) -> dict[str, Any] | None:
    for event in list_calendar_events():
        if event_meet_url(event) == meet_url:
            return event
    return None


def fmt_event_time(event: dict[str, Any]) -> str:
    start = event_start(event)
    end = event_end(event)
    if not start:
        return "زمان نامشخص"
    if end:
        return f"{start.strftime('%Y-%m-%d %H:%M')} تا {end.strftime('%H:%M')}"
    return start.strftime("%Y-%m-%d %H:%M")


async def launch_meeting(event: dict[str, Any], req: dict[str, Any], meet_url: str) -> bool:
    event_id = event.get("id") or str(uuid.uuid4())
    chat_id = str(req["chat_id"])
    payload = {
        "bearerToken": "beonmeet-local",
        "url": meet_url,
        "name": BOT_DISPLAY_NAME,
        "teamId": "beonmeet",
        "timezone": "UTC",
        "userId": chat_id,
        "eventId": event_id,
        "botId": event_id,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{MEETING_BOT_URL}/google/join", json=payload)
        if r.status_code == 202:
            state["launched_events"][event_id] = {
                "meet_url": meet_url,
                "chat_id": chat_id,
                "launched_at": datetime.now(timezone.utc).isoformat(),
                "status": "joining",
            }
            await save_state()
            await tg_text(chat_id, f"⏳ درخواست ورود به جلسه ارسال شد. دارم وارد می‌شم…\n{meet_url}")
            return True
        if r.status_code == 409:
            return False
        await tg_text(chat_id, f"⚠️ فعلاً نتونستم وارد جلسه بشم. خودم دوباره امتحان می‌کنم.\n{meet_url}")
    except Exception:
        return False
    return False


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
                    launched = state["launched_events"].get(event_id)
                    if launched:
                        status = str(launched.get("status") or "joining")
                        launched_at_raw = launched.get("launched_at")
                        launched_at = isoparse(launched_at_raw) if launched_at_raw else None
                        if status == "recording":
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
                            "• پیش نویس صورتجلسه"
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
                                    "• پیش نویس صورتجلسه\n\n"
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
                    )
                    continue
                if text.strip().lower() == "/now":
                    state.setdefault("pending_now", {})[str(chat_id)] = True
                    await save_state()
                    await tg_text(chat_id, "باشه. حالا لینک Google Meet رو بفرست تا همین الان واردش بشم.")
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
                        launched = await launch_meeting(synthetic_event, state["requests"][meet_url], meet_url)
                        if not launched:
                            await tg_text(chat_id, "⏳ درخواست ورود ثبت شد. اگه رکوردر مشغول باشه، به محض آزاد شدن دوباره امتحان می‌کنم.")
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


@app.post("/internal/recording-ready")
async def recording_ready(
    request: Request,
    x_beonmeet_secret: str = Header(...),
) -> dict[str, Any]:
    if x_beonmeet_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    raw_path = Path(str(data.get("filePath", ""))).resolve()
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
        await tg_text(chat_id, "✅ جلسه تموم شد. دارم فایل ضبط شده رو برات می‌فرستم…")
        await send_recording_to_recipients(recipients, raw_path, filename)

        await asyncio.to_thread(
            record_recording,
            chat_id,
            meeting_link,
            filename,
            int(data.get("size") or raw_path.stat().st_size),
            int(data.get("duration") or 0),
        )

        # Premium: create a separate MP3 in RAM and deliver it to the requester and admin.
        if await asyncio.to_thread(is_premium, chat_id):
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
            finally:
                audio_path.unlink(missing_ok=True)

        raw_path.unlink(missing_ok=True)
        return {"ok": True, "admin_copy": bool(ADMINUSER), "premium": await asyncio.to_thread(is_premium, chat_id)}
    except Exception as exc:
        await tg_text(chat_id, "⚠️ ضبط تموم شده ولی ارسالش به تلگرام خطا خورد. فایل فعلاً فقط توی حافظه موقت نگه داشته شده تا بتونم دوباره بفرستم.")
        raise HTTPException(status_code=502, detail=str(exc))
