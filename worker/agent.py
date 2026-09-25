import asyncio
import os
import socket
import uuid

import httpx

CONTROLLER = os.environ.get("CONTROLLER_BASE_URL", "https://beonmeet.smarbiz.sbs").rstrip("/")
SECRET = os.environ["INTERNAL_SECRET"]
MEETING_BOT = os.environ.get("MEETING_BOT_URL", "http://meeting-bot:3000").rstrip("/")
WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
WORKER_POOL = os.environ.get("WORKER_POOL", "free").strip().lower()
WORKER_SLOTS = max(1, int(os.environ.get("WORKER_SLOTS", "4")))
RECORDER_ACCOUNT_ID = os.environ.get("RECORDER_ACCOUNT_ID", "primary").strip() or "primary"

HEADERS = {"x-beonmeet-secret": SECRET}


async def local_capacity(client: httpx.AsyncClient) -> dict:
    try:
        response = await client.get(f"{MEETING_BOT}/capacity")
        response.raise_for_status()
        data = (response.json() or {}).get("data") or {}
        return {
            "running_jobs": int(data.get("runningJobs") or 0),
            "max_jobs": int(data.get("maxConcurrentJobs") or WORKER_SLOTS),
            "available_slots": int(data.get("availableSlots") or 0),
        }
    except Exception:
        return {
            "running_jobs": WORKER_SLOTS,
            "max_jobs": WORKER_SLOTS,
            "available_slots": 0,
        }


async def heartbeat(client: httpx.AsyncClient, capacity: dict) -> None:
    await client.post(
        f"{CONTROLLER}/internal/worker/heartbeat",
        headers=HEADERS,
        json={
            "worker_id": WORKER_ID,
            "pool": WORKER_POOL,
            "slots": WORKER_SLOTS,
            "active_jobs": int(capacity.get("running_jobs") or 0),
            "max_jobs": int(capacity.get("max_jobs") or WORKER_SLOTS),
            "available_slots": int(capacity.get("available_slots") or 0),
            "account_id": RECORDER_ACCOUNT_ID,
        },
    )


async def claim(client: httpx.AsyncClient) -> dict | None:
    response = await client.post(
        f"{CONTROLLER}/internal/worker/claim",
        headers=HEADERS,
        json={
            "worker_id": WORKER_ID,
            "pool": WORKER_POOL,
            "slots": WORKER_SLOTS,
            "account_id": RECORDER_ACCOUNT_ID,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("job"):
        return None
    return payload


async def accepted(client: httpx.AsyncClient, claim_id: str) -> None:
    response = await client.post(
        f"{CONTROLLER}/internal/worker/accepted",
        headers=HEADERS,
        json={"claim_id": claim_id},
    )
    response.raise_for_status()


async def requeue(client: httpx.AsyncClient, claim_id: str, reason: str) -> None:
    try:
        await client.post(
            f"{CONTROLLER}/internal/worker/requeue",
            headers=HEADERS,
            json={"claim_id": claim_id, "reason": reason[:500]},
        )
    except Exception:
        pass


async def run() -> None:
    if WORKER_POOL not in {"free", "premium"}:
        raise RuntimeError("WORKER_POOL must be free or premium")

    timeout = httpx.Timeout(35.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        print(
            f"BeOnMeet worker agent started: id={WORKER_ID} "
            f"pool={WORKER_POOL} slots={WORKER_SLOTS} account={RECORDER_ACCOUNT_ID}",
            flush=True,
        )
        heartbeat_due = 0.0
        loop = asyncio.get_running_loop()

        while True:
            try:
                now = loop.time()
                capacity = await local_capacity(client)
                if now >= heartbeat_due:
                    await heartbeat(client, capacity)
                    heartbeat_due = now + 10.0

                if int(capacity.get("available_slots") or 0) <= 0:
                    await asyncio.sleep(1)
                    continue

                payload = await claim(client)
                if not payload:
                    await asyncio.sleep(1)
                    continue

                claim_id = str(payload.get("claim_id") or "")
                job = payload["job"]
                try:
                    response = await client.post(f"{MEETING_BOT}/google/join", json=job)
                    if response.status_code == 202:
                        await accepted(client, claim_id)
                    else:
                        await requeue(
                            client,
                            claim_id,
                            f"meeting-bot returned {response.status_code}: {response.text[:300]}",
                        )
                except Exception as exc:
                    await requeue(client, claim_id, repr(exc))

            except Exception as exc:
                print("worker agent loop error:", repr(exc), flush=True)
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(run())
