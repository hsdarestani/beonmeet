#!/usr/bin/env python3
"""Ephemeral, private, Basic-authenticated noVNC login to existing BeOnMeet Chrome.

Only the meeting owner signs in to Google. Never handle Google credentials.
Credentials are generated on host and sent only via private Telegram DM;
no secret appears in GitHub, public Actions logs, or shell command arguments.
Automatic expiry removes Nginx route and password even if the owner forgets.
"""
from __future__ import annotations

import base64
import fcntl
import grp
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

SITE = Path("/etc/nginx/sites-enabled/shared-vps-https-beonmeet.smarbiz.sbs")
ROOT = Path("/opt/beonmeet/.temporary-google-login")
STATE = ROOT / "active.json"
MANAGER = ROOT / "manager.py"
LOCK = Path("/var/lock/pars-vds-bot-deploy.lock")
HOST = "beonmeet.smarbiz.sbs"
MEET_CODE = "cru-ggpe-nwi"
TTL_MINUTES = 45


def execute(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=25)


def read_bot_config() -> tuple[str, str]:
    conf: dict[str, str] = {}
    for line in Path("/opt/beonmeet/.env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_API_BASE"):
            conf[key.strip()] = value.strip().strip("'\"")
    token = conf.get("TELEGRAM_BOT_TOKEN", "")
    if len(token) < 25:
        raise RuntimeError("Bot Telegram token is unavailable")
    base = conf.get("TELEGRAM_API_BASE") or "https://api.telegram.org"
    if not base.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise RuntimeError("Unexpected Telegram API host")
    return token, base.rstrip("/")


def owner_chat_id() -> str:
    state = json.loads(Path("/opt/beonmeet/data/state.json").read_text())
    ids: set[str] = set()
    for link, req in (state.get("requests") or {}).items():
        if MEET_CODE in str(link) and isinstance(req, dict):
            cid = str(req.get("chat_id") or "").strip()
            if cid.isdigit():
                ids.add(cid)
    if len(ids) != 1:
        raise RuntimeError("Cannot uniquely identify testing owner's chat")
    return ids.pop()


def health() -> None:
    for port in (8109, 9124, 9126):
        path = "/health" if port == 8109 else "/capacity"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=6
        ) as response:
            data = json.load(response)
        if port == 8109:
            if not data.get("ok"):
                raise RuntimeError("Controller unhealthy")
            for key in ("active_delivery_jobs", "pending_delivery_jobs",
                        "free_queue", "premium_queue"):
                if int(data.get(key) or 0):
                    raise RuntimeError("Delivery or meeting queue active")
        else:
            worker = data.get("data") or data
            if int(worker.get("runningJobs") or 0):
                raise RuntimeError("Recorder active")
    for name in ("camcam-shared-api-1", "camcam-shared-pet-1",
                 "camcam-shared-archive-1", "camcam-shared-petarchive-1"):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
            text=True, capture_output=True, timeout=8
        )
        if result.returncode != 0 or result.stdout.strip() != "healthy":
            raise RuntimeError("Neighbor service not healthy")
    with urllib.request.urlopen("http://127.0.0.1:6081/vnc.html", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Internal browser UI unavailable")


def atomically_write_config(value: str) -> None:
    stat = SITE.stat()
    tmp = SITE.with_name(SITE.name + ".login-tmp")
    if tmp.exists():
        raise RuntimeError("Temporary nginx config collision")
    try:
        tmp.write_text(value)
        os.chmod(tmp, stat.st_mode & 0o777)
        os.chown(tmp, stat.st_uid, stat.st_gid)
        os.replace(tmp, SITE)
    finally:
        tmp.unlink(missing_ok=True)


def probe(route: str, password: str | None) -> int:
    context = ssl._create_unverified_context()  # Test *local* TLS listener only.
    conn = http.client.HTTPSConnection("127.0.0.1", 443, timeout=7, context=context)
    headers = {"Host": HOST}
    if password is not None:
        value = base64.b64encode(f"setup:{password}".encode()).decode()
        headers["Authorization"] = "Basic " + value
    try:
        conn.request("GET", route + "vnc.html", headers=headers)
        resp = conn.getresponse()
        resp.read(128)
        return resp.status
    finally:
        conn.close()


def cleanup_unlocked() -> None:
    if not STATE.exists():
        print("LOGIN_GATEWAY_ALREADY_INACTIVE")
        return
    state = json.loads(STATE.read_text())
    begin = state["begin"]
    end = state["end"]
    text = SITE.read_text()
    if text.count(begin) != 1 or text.count(end) != 1:
        raise RuntimeError("Gateway marker mismatch; refuse unrelated nginx edits")
    prefix, rest = text.split(begin, 1)
    _, suffix = rest.split(end, 1)
    revised = prefix + suffix
    atomically_write_config(revised)
    try:
        execute(["nginx", "-t"])
        execute(["systemctl", "reload", "nginx"])
    except Exception:
        atomically_write_config(text)
        execute(["nginx", "-t"])
        execute(["systemctl", "reload", "nginx"])
        raise
    Path(state["passwd_file"]).unlink(missing_ok=True)
    STATE.unlink(missing_ok=True)
    print("SECURE_GOOGLE_LOGIN_ROUTE_REMOVED")


def send_telegram(message: str) -> None:
    token, base = read_bot_config()
    owner = owner_chat_id()
    payload = urllib.parse.urlencode({
        "chat_id": owner,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode()
    # Telegram credentials are never included in an exception or printed.
    request = urllib.request.Request(
        f"{base}/bot{token}/sendMessage",
        data=payload, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
            if not result.get("ok"):
                raise RuntimeError("Telegram API refused the private setup message")
    except Exception:
        raise RuntimeError("Private Telegram setup message could not be delivered") from None


def setup() -> None:
    if STATE.exists():
        raise RuntimeError("A temporary login session already exists")
    health()
    # Validate destination and Telegram routing BEFORE changing proxy.
    read_bot_config()
    owner_chat_id()
    site = SITE.read_text()
    assert site.count("server_name beonmeet.smarbiz.sbs;") == 1
    anchor = "    location / {"
    assert site.count(anchor) == 1
    assert "location ^~ /beonmeet-login-" not in site
    route_id = secrets.token_urlsafe(17).replace("-", "a").replace("_", "b")
    route = f"/beonmeet-login-{route_id}/"
    username = "setup"
    password = secrets.token_urlsafe(25)
    passwd_file = ROOT / ("auth-" + route_id + ".htpasswd")
    # Password is sent through stdin (not argv or CI logs).
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"], input=password + "\n",
        capture_output=True, text=True, timeout=8, check=True
    )
    passwd_file.write_text(username + ":" + result.stdout.strip() + "\n")
    os.chown(passwd_file, 0, grp.getgrnam("www-data").gr_gid)
    os.chmod(passwd_file, 0o640)
    begin = f"    # BEONMEET_PRIVATE_LOGIN_BEGIN_{route_id}\n"
    end = f"    # BEONMEET_PRIVATE_LOGIN_END_{route_id}\n"
    block = (
        begin
        + f"    location ^~ {route} {{\n"
        + '        auth_basic "Temporary BeOnMeet Google login";\n'
        + f"        auth_basic_user_file {passwd_file};\n"
        + "        access_log off;\n"
        + '        add_header Cache-Control "no-store" always;\n'
        + '        add_header Referrer-Policy "no-referrer" always;\n'
        + "        proxy_http_version 1.1;\n"
        + "        proxy_set_header Upgrade $http_upgrade;\n"
        + '        proxy_set_header Connection "upgrade";\n'
        + "        proxy_set_header Host $host;\n"
        + "        proxy_set_header X-Forwarded-Proto https;\n"
        + "        proxy_read_timeout 1200s;\n"
        + "        proxy_pass http://127.0.0.1:6081/;\n"
        + "    }\n"
        + end
    )
    original = site
    try:
        atomically_write_config(site.replace(anchor, block + anchor, 1))
        execute(["nginx", "-t"])
        execute(["systemctl", "reload", "nginx"])
        # No public access possible without Basic Auth.
        if probe(route, None) != 401 or probe(route, password) != 200:
            raise RuntimeError("HTTPS proxy was not verified as locked down")
        STATE.write_text(json.dumps({
            "begin": begin, "end": end,
            "passwd_file": str(passwd_file),
            "created_epoch": int(time.time()),
            "expires_epoch": int(time.time()) + 60 * TTL_MINUTES,
        }))
        os.chmod(STATE, 0o600)
        execute([
            "systemd-run", "--quiet",
            "--unit=beonmeet-login-expiry",
            f"--on-active={TTL_MINUTES}m",
            "/usr/bin/python3", str(MANAGER), "cleanup"
        ])
        url = (f"https://{HOST}{route}vnc.html?autoconnect=true"
               f"&path={route.lstrip('/')}websockify")
        message = (
            "🔐 دسترسی موقت ورود Google برای BeOnMeet آماده است.\n\n"
            f"لینک امن (فقط {TTL_MINUTES} دقیقه):\n{url}\n\n"
            f"نام کاربری: {username}\nرمز موقت: {password}\n\n"
            "در این صفحه، مرورگر خود ربات را می‌بینی. با حساب Google "
            "اختصاصی ضبط‌کننده وارد شو و تأیید دومرحله‌ای را انجام بده. "
            "رمز Google را برای کسی نفرست.\n\n"
            "بعد از اینکه در مرورگر سرور وارد حساب Google شدی، "
            "در همین گفت‌وگو به من بگو «وارد شدم». "
            "این لینک بعد از انقضا خودکار بسته می‌شود."
        )
        send_telegram(message)
        print("SECURE_LOGIN_LINK_SENT_ONLY_TO_REQUESTING_TELEGRAM_CHAT")
        print("NGINX_BASIC_AUTH_401_AND_200_VERIFIED")
        print("LOGIN_GATEWAY_EXPIRY_SCHEDULED",TTL_MINUTES)
    except Exception:
        if STATE.exists():
            # Undo fully if setup delivery fails.
            try:cleanup_unlocked()
            except Exception:pass
        elif begin in SITE.read_text() and end in SITE.read_text():
            atomically_write_config(original)
            try:
                execute(["nginx", "-t"])
                execute(["systemctl", "reload", "nginx"])
            except Exception:pass
        passwd_file.unlink(missing_ok=True)
        raise


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("Root access required")
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(ROOT, 0o700)
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in ("setup", "cleanup"):
        raise SystemExit("usage: manager.py setup|cleanup")
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if action == "setup":
            setup()
        else:
            cleanup_unlocked()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # No credentials or URLs in public GitHub Actions logs.
        print("SECURE_LOGIN_MANAGER_ERROR",type(exc).__name__)
        sys.exit(1)
