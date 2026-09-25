import asyncio
import json
import math
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import redis
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse

from scaling_policy import bounded_scale_up

router = APIRouter()

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "").strip()
AUTOSCALE_ENABLED = os.environ.get("AUTOSCALE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
HETZNER_API_BASE = "https://api.hetzner.cloud/v1"
CONTROLLER_PUBLIC_URL = os.environ.get("CONTROLLER_PUBLIC_URL", "https://beonmeet.smarbiz.sbs").rstrip("/")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

SERVER_TYPE = os.environ.get("AUTOSCALE_SERVER_TYPE", "cpx31")
SERVER_IMAGE = os.environ.get("AUTOSCALE_SERVER_IMAGE", "ubuntu-24.04")
SERVER_LOCATION = os.environ.get("AUTOSCALE_SERVER_LOCATION", "nbg1")
WORKER_SLOTS = max(1, int(os.environ.get("AUTOSCALE_WORKER_SLOTS", "3")))
MAX_FREE_WORKERS = max(0, int(os.environ.get("AUTOSCALE_MAX_FREE_WORKERS", "6")))
MAX_PREMIUM_WORKERS = max(0, int(os.environ.get("AUTOSCALE_MAX_PREMIUM_WORKERS", "3")))
MIN_FREE_WORKERS = max(0, int(os.environ.get("AUTOSCALE_MIN_FREE_WORKERS", "0")))
MIN_PREMIUM_WORKERS = max(0, int(os.environ.get("AUTOSCALE_MIN_PREMIUM_WORKERS", "0")))
IDLE_MINUTES = max(5, int(os.environ.get("AUTOSCALE_IDLE_MINUTES", "20")))
SCALE_UP_COOLDOWN = max(20, int(os.environ.get("AUTOSCALE_SCALE_UP_COOLDOWN_SECONDS", "60")))
BOOT_TIMEOUT_MINUTES = max(5, int(os.environ.get("AUTOSCALE_BOOT_TIMEOUT_MINUTES", "15")))

PROFILE_ROOT = Path(os.environ.get("AUTOSCALE_PROFILE_ROOT", "/bootstrap"))
PROFILE_DIR = PROFILE_ROOT / "chrome-profile"
ACCOUNT_PROFILE_ROOT = PROFILE_ROOT / "accounts"
MAX_WORKERS_PER_ACCOUNT = max(1, int(os.environ.get("AUTOSCALE_MAX_WORKERS_PER_ACCOUNT", "3")))

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=5,
    health_check_interval=30,
)


def enabled() -> bool:
    return bool(AUTOSCALE_ENABLED and HETZNER_API_TOKEN and INTERNAL_SECRET)


def _bootstrap_key(token: str) -> str:
    return f"beonmeet:autoscale:bootstrap:{token}"


def _idle_key(worker_id: str) -> str:
    return f"beonmeet:autoscale:idle:{worker_id}"


def _worker_key(worker_id: str) -> str:
    return f"beonmeet:worker:{worker_id}"


def available_account_profiles() -> dict[str, Path]:
    profiles: dict[str, Path] = {}
    if (PROFILE_DIR / "Default").exists():
        profiles["primary"] = PROFILE_DIR
    if ACCOUNT_PROFILE_ROOT.exists():
        for path in sorted(ACCOUNT_PROFILE_ROOT.iterdir()):
            if path.is_dir() and (path / "Default").exists():
                profiles[path.name] = path
    return profiles


def profile_status() -> dict[str, Any]:
    profiles = available_account_profiles()
    return {
        "count": len(profiles),
        "ids": sorted(profiles.keys()),
    }


def _select_account_id(existing_servers: list[dict[str, Any]]) -> str:
    profiles = available_account_profiles()
    if not profiles:
        raise RuntimeError("No signed-in recorder account profile is available")

    counts = {account_id: 0 for account_id in profiles}
    for server in existing_servers:
        account_id = str((server.get("labels") or {}).get("account-id") or "primary")
        if account_id in counts:
            counts[account_id] += 1

    ranked = sorted(counts.items(), key=lambda item: (item[1], item[0]))
    if len(ranked) == 1:
        return ranked[0][0]

    for account_id, count in ranked:
        if count < MAX_WORKERS_PER_ACCOUNT:
            return account_id
    return ranked[0][0]


def _load_bootstrap(token: str) -> dict[str, Any]:
    try:
        raw = redis_client.get(_bootstrap_key(token))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Bootstrap store unavailable: {exc}")
    if not raw:
        raise HTTPException(status_code=404, detail="Bootstrap token expired")
    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid bootstrap state")


@router.get("/internal/autoscale/env/{token}", response_class=PlainTextResponse)
async def bootstrap_env(token: str) -> PlainTextResponse:
    entry = _load_bootstrap(token)
    payload = "\n".join([
        f"CONTROLLER_BASE_URL={CONTROLLER_PUBLIC_URL}",
        f"INTERNAL_SECRET={INTERNAL_SECRET}",
        f"WORKER_ID={entry['worker_id']}",
        f"WORKER_POOL={entry['pool']}",
        f"WORKER_SLOTS={entry['slots']}",
        f"RECORDER_ACCOUNT_ID={entry.get('account_id', 'primary')}",
        "",
    ])
    return PlainTextResponse(
        payload,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/internal/autoscale/profile/{token}")
async def bootstrap_profile(token: str) -> StreamingResponse:
    entry = _load_bootstrap(token)
    account_id = str(entry.get("account_id") or "primary")
    profiles = available_account_profiles()
    profile_dir = profiles.get(account_id)
    if not profile_dir or not profile_dir.exists():
        raise HTTPException(status_code=503, detail="Signed-in Chrome profile is unavailable")

    proc = subprocess.Popen(
        [
            "tar",
            "-C", str(profile_dir.parent),
            f"--transform=s|^{profile_dir.name}|chrome-profile|",
            "-czf", "-",
            profile_dir.name,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def stream():
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.stdout:
                proc.stdout.close()
            code = proc.wait(timeout=30)
            if code != 0 and proc.stderr:
                print("profile archive error:", proc.stderr.read().decode(errors="ignore"), flush=True)

    return StreamingResponse(
        stream(),
        media_type="application/gzip",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": 'attachment; filename="chrome-profile.tar.gz"',
        },
    )


async def _hetzner(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {HETZNER_API_TOKEN}"
    response = await client.request(method, f"{HETZNER_API_BASE}{path}", headers=headers, **kwargs)
    response.raise_for_status()
    return response


async def _list_servers(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await _hetzner(
        client,
        "GET",
        "/servers",
        params={"label_selector": "managed-by=beonmeet", "per_page": 50},
    )
    return list((response.json() or {}).get("servers") or [])


async def _delete_server(client: httpx.AsyncClient, server_id: int) -> None:
    await _hetzner(client, "DELETE", f"/servers/{server_id}")


def _cloud_init(token: str) -> str:
    repo = "https://github.com/hsdarestani/beonmeet.git"
    return f"""#cloud-config
package_update: true
packages:
  - git
  - curl
  - ca-certificates
  - tar
  - python3
runcmd:
  - |
      set -euo pipefail
      rm -rf /opt/beonmeet-worker
      git clone --depth 1 {repo} /opt/beonmeet-worker
      cd /opt/beonmeet-worker
      curl -fsS --retry 8 --retry-delay 5 \
        {CONTROLLER_PUBLIC_URL}/internal/autoscale/env/{token} \
        -o worker.env
      curl -fsS --retry 8 --retry-delay 5 \
        {CONTROLLER_PUBLIC_URL}/internal/autoscale/profile/{token} \
        -o /tmp/beonmeet-profile.tar.gz
      tar -xzf /tmp/beonmeet-profile.tar.gz -C /opt/beonmeet-worker
      rm -f /tmp/beonmeet-profile.tar.gz
      chmod 600 worker.env
      chmod +x worker/bootstrap.sh
      ./worker/bootstrap.sh /opt/beonmeet-worker
      sed -ri 's/^#?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config || true
      systemctl reload ssh || systemctl reload sshd || true
"""


async def _create_server(
    client: httpx.AsyncClient,
    pool: str,
    existing_servers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    worker_id = f"beonmeet-{pool}-{secrets.token_hex(4)}"
    account_id = _select_account_id(existing_servers or [])
    entry = {
        "worker_id": worker_id,
        "pool": pool,
        "slots": WORKER_SLOTS,
        "account_id": account_id,
        "created_at": time.time(),
    }
    redis_client.setex(_bootstrap_key(token), 1800, json.dumps(entry, separators=(",", ":")))

    payload = {
        "name": worker_id,
        "server_type": SERVER_TYPE,
        "image": SERVER_IMAGE,
        "location": SERVER_LOCATION,
        "user_data": _cloud_init(token),
        "labels": {
            "managed-by": "beonmeet",
            "service": "recorder",
            "pool": pool,
            "worker-id": worker_id,
            "account-id": account_id,
        },
    }
    response = await _hetzner(client, "POST", "/servers", json=payload)
    data = response.json() or {}
    server = data.get("server") or {}
    print(
        f"autoscaler created {pool} worker {worker_id} "
        f"server_id={server.get('id')} account={account_id} type={SERVER_TYPE} location={SERVER_LOCATION}",
        flush=True,
    )
    return server


def _server_pool(server: dict[str, Any]) -> str:
    return str((server.get("labels") or {}).get("pool") or "free").lower()


def _server_worker_id(server: dict[str, Any]) -> str:
    labels = server.get("labels") or {}
    return str(labels.get("worker-id") or server.get("name") or "")


def _server_age_seconds(server: dict[str, Any]) -> float:
    created = str(server.get("created") or "")
    if not created:
        return 0.0
    try:
        from dateutil.parser import isoparse
        return max(0.0, time.time() - isoparse(created).timestamp())
    except Exception:
        return 0.0


def _runtime(worker_id: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(_worker_key(worker_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _idle_for(worker_id: str, active_jobs: int, queue_empty: bool) -> float:
    key = _idle_key(worker_id)
    now = time.time()
    try:
        if active_jobs > 0 or not queue_empty:
            redis_client.delete(key)
            return 0.0
        raw = redis_client.get(key)
        if not raw:
            redis_client.set(key, str(now))
            return 0.0
        return max(0.0, now - float(raw))
    except Exception:
        return 0.0


async def autoscale_loop() -> None:
    if not enabled():
        print("Hetzner autoscaler disabled", flush=True)
        return

    print(
        "Hetzner autoscaler enabled "
        f"type={SERVER_TYPE} location={SERVER_LOCATION} slots={WORKER_SLOTS}",
        flush=True,
    )
    last_scale_up = {"free": 0.0, "premium": 0.0}

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                health_response = await client.get("http://127.0.0.1:8000/health")
                health_response.raise_for_status()
                health = health_response.json()

                free_queue = int(health.get("free_queue") or 0)
                premium_queue = int(health.get("premium_queue") or 0)

                servers = await _list_servers(client)
                managed = [
                    s for s in servers
                    if str((s.get("labels") or {}).get("service") or "") == "recorder"
                ]

                by_pool = {
                    "free": [s for s in managed if _server_pool(s) == "free"],
                    "premium": [s for s in managed if _server_pool(s) == "premium"],
                }

                # Remove workers that never managed to bootstrap.
                for pool in ("free", "premium"):
                    for server in list(by_pool[pool]):
                        worker_id = _server_worker_id(server)
                        runtime = _runtime(worker_id)
                        if (
                            not runtime
                            and _server_age_seconds(server) > BOOT_TIMEOUT_MINUTES * 60
                        ):
                            print(f"autoscaler deleting stale boot worker {worker_id}", flush=True)
                            await _delete_server(client, int(server["id"]))
                            by_pool[pool].remove(server)

                now = time.time()

                # Premium queue gets its own reserved workers. Free queue scales
                # only general workers. This keeps Premium capacity isolated.
                policy = [
                    ("premium", premium_queue, MAX_PREMIUM_WORKERS),
                    ("free", free_queue, MAX_FREE_WORKERS),
                ]
                for pool, queue_size, max_workers in policy:
                    runtimes = [
                        _runtime(_server_worker_id(s))
                        for s in by_pool[pool]
                    ]
                    available = sum(
                        max(0, int((rt or {}).get("available_slots") or 0))
                        for rt in runtimes
                    )
                    to_create = bounded_scale_up(
                        queue_size=queue_size,
                        available_slots=available,
                        worker_slots=WORKER_SLOTS,
                        current_workers=len(by_pool[pool]),
                        max_workers=max_workers,
                        per_cycle_limit=2,
                    )

                    if (
                        to_create > 0
                        and now - last_scale_up[pool] >= SCALE_UP_COOLDOWN
                    ):
                        for _ in range(to_create):
                            server = await _create_server(client, pool, managed)
                            managed.append(server)
                            by_pool[pool].append(server)
                        last_scale_up[pool] = now

                # Scale down only workers with an exact zero active-job count.
                for pool, queue_size, min_workers in (
                    ("premium", premium_queue, MIN_PREMIUM_WORKERS),
                    ("free", free_queue, MIN_FREE_WORKERS),
                ):
                    if queue_size > 0 or len(by_pool[pool]) <= min_workers:
                        continue
                    for server in sorted(by_pool[pool], key=_server_age_seconds, reverse=True):
                        if len(by_pool[pool]) <= min_workers:
                            break
                        worker_id = _server_worker_id(server)
                        runtime = _runtime(worker_id)
                        if not runtime:
                            continue
                        active_jobs = int(runtime.get("active_jobs") or 0)
                        idle_seconds = _idle_for(worker_id, active_jobs, queue_empty=True)
                        if active_jobs == 0 and idle_seconds >= IDLE_MINUTES * 60:
                            print(
                                f"autoscaler removing idle {pool} worker {worker_id} "
                                f"after {int(idle_seconds)}s idle",
                                flush=True,
                            )
                            await _delete_server(client, int(server["id"]))
                            redis_client.delete(_idle_key(worker_id))
                            by_pool[pool].remove(server)
                            break

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print("autoscaler loop error:", repr(exc), flush=True)

            await asyncio.sleep(15)
