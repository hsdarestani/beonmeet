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

app = FastAPI(title="BeOnMeet Controller")

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
TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
MEETING_BOT_URL = os.environ.get("MEETING_BOT_URL", "http://meeting-bot:3000").rstrip("/")
INTERNAL_SECRET = os.environ["INTERNAL_SECRET"]
RECORDING_ROOT = Path(os.environ.get("RECORDING_TMP_DIR", "/recordings")).resolve()
BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "BeOnMeet Recorder")
CALENDAR_POLL_SECONDS = int(os.environ.get("CALENDAR_POLL_SECONDS", "30"))

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
    return match.group(0).split("?")[0].lower()


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
        return "unknown time"
    if end:
        return f"{start.astimezone().strftime('%Y-%m-%d %H:%M')} to {end.astimezone().strftime('%H:%M')}"
    return start.astimezone().strftime("%Y-%m-%d %H:%M")


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
            }
            await save_state()
            await tg_text(chat_id, f"🎥 Recording started\n{meet_url}")
            return True
        if r.status_code == 409:
            return False
        await tg_text(chat_id, f"⚠️ Recorder could not join yet. It will retry automatically.\n{meet_url}")
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
                    if not event_id or event_id in state["launched_events"]:
                        continue
                    start = event_start(event)
                    end = event_end(event)
                    if not start:
                        continue
                    if end and now > end:
                        continue
                    live_until = (end + timedelta(minutes=5)) if end else (start + timedelta(hours=3))
                    if start - timedelta(minutes=2) <= now <= live_until:
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
                chat_id = chat.get("id")
                text = msg.get("text") or msg.get("caption") or ""
                if not chat_id:
                    continue
                if text.startswith("/start"):
                    auth_status = "✅ Calendar connected" if TOKEN_FILE.exists() else f"⚠️ Calendar not connected yet\nhttps://{DOMAIN}/auth/google"
                    await tg_text(
                        chat_id,
                        "BeOnMeet Recorder\n\n"
                        "Send me the Google Meet link you want recorded. "
                        f"Also invite {BOT_EMAIL} to that Calendar event. "
                        "At the meeting time I will join, record, and send the result back here.\n\n"
                        + auth_status,
                    )
                    continue
                force_now = text.strip().lower().startswith("/now")
                meet_url = normalize_meet_url(text)
                if meet_url:
                    state["requests"][meet_url] = {
                        "chat_id": str(chat_id),
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await save_state()

                    if force_now:
                        synthetic_event = {
                            "id": f"manual-{uuid.uuid4()}",
                            "start": {"dateTime": datetime.now(timezone.utc).isoformat()},
                            "end": {"dateTime": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()},
                        }
                        launched = await launch_meeting(synthetic_event, state["requests"][meet_url], meet_url)
                        if not launched:
                            await tg_text(chat_id, "⏳ Join request is queued or the recorder is busy. I will retry from the calendar watcher if this link is also scheduled.")
                        continue

                    try:
                        matched_event = await asyncio.to_thread(find_calendar_event_for_meet, meet_url)
                    except Exception as exc:
                        print("calendar lookup error after Telegram request:", repr(exc), flush=True)
                        await tg_text(
                            chat_id,
                            "⚠️ I saved the request, but I could not read Google Calendar right now. "
                            "Please try again in a moment.",
                        )
                        continue

                    if matched_event:
                        when = fmt_event_time(matched_event)
                        await tg_text(
                            chat_id,
                            f"✅ Request saved and Calendar event found\n{meet_url}\n🕒 {when}",
                        )
                        now = datetime.now(timezone.utc)
                        start = event_start(matched_event)
                        end = event_end(matched_event)
                        live_until = (end + timedelta(minutes=5)) if end else ((start + timedelta(hours=3)) if start else now)
                        if start and start - timedelta(minutes=2) <= now <= live_until:
                            await launch_meeting(matched_event, state["requests"][meet_url], meet_url)
                    else:
                        await tg_text(
                            chat_id,
                            f"⚠️ Request saved, but I cannot see this Meet in {BOT_EMAIL}'s Google Calendar yet.\n\n"
                            f"Invite {BOT_EMAIL} to the Calendar event and make sure the invitation is actually added to that account's calendar. "
                            "Then send the link again.\n\n"
                            "If the meeting is already live and you want to force an immediate join, send:\n"
                            f"/now {meet_url}",
                        )
                else:
                    await tg_text(chat_id, "Send a Google Meet link, for example:\nhttps://meet.google.com/abc-defg-hij")
        except Exception as exc:
            print("telegram loop error:", repr(exc), flush=True)
            await asyncio.sleep(5)


async def send_recording(chat_id: str, path: Path, filename: str) -> None:
    max_cloud = 49 * 1024 * 1024
    size = path.stat().st_size
    if size <= max_cloud or TELEGRAM_API_BASE != "https://api.telegram.org":
        with path.open("rb") as fp:
            await telegram(
                "sendDocument",
                {"chat_id": chat_id, "caption": "🎥 Meeting recording"},
                {"document": (filename, fp, "video/webm" if filename.endswith(".webm") else "video/mp4")},
            )
        return

    # Cloud Bot API has a small upload limit. Create playable compressed parts in RAM.
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
    await tg_text(chat_id, f"Recording is larger than Telegram Bot API cloud limit, so it is being sent in {len(parts)} playable parts.")
    for idx, part in enumerate(parts, 1):
        with part.open("rb") as fp:
            await telegram(
                "sendDocument",
                {"chat_id": chat_id, "caption": f"🎥 Meeting recording {idx}/{len(parts)}"},
                {"document": (part.name, fp, "video/mp4")},
            )
        part.unlink(missing_ok=True)


@app.on_event("startup")
async def startup() -> None:
    load_state()
    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(telegram_loop())
    asyncio.create_task(calendar_loop())


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "calendar_connected": TOKEN_FILE.exists(),
        "bot_email": BOT_EMAIL,
    }


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    status = "connected" if TOKEN_FILE.exists() else "not connected"
    return f"<h1>BeOnMeet</h1><p>Google Calendar: {status}</p><p><a href='/auth/google'>Connect Calendar</a></p>"


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
    return "<h2>Google Calendar connected successfully.</h2><p>You can close this page and return to Telegram.</p>"


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
    try:
        await tg_text(chat_id, "✅ Meeting ended. Uploading the recording now…")
        await send_recording(chat_id, raw_path, filename)
        raw_path.unlink(missing_ok=True)
        return {"ok": True}
    except Exception as exc:
        await tg_text(chat_id, "⚠️ Recording finished, but Telegram upload failed. I will keep it in temporary RAM until the service restarts.")
        raise HTTPException(status_code=502, detail=str(exc))
