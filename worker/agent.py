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

HEADERS = {"x-beonmeet-secret": SECRET}


async def heartbeat(client: httpx.AsyncClient) -> None:
    await client.post(
        f"{CONTROLLER}/internal/worker/heartbeat",
        headers=HEADERS,
        json={
            "worker_id": WORKER_ID,
            "pool": WORKER_POOL,
            "slots": WORKER_SLOTS,
        },
    )


async def local_busy(client: httpx.AsyncClient) -> bool:
    try:
        response = await client.get(f"{MEETING_BOT}/isbusy")
        response.raise_for_status()
        return bool((response.json() or {}).get("data"))
    except Exception:
        return True


async def claim(client: httpx.AsyncClient) -> dict | None:
    response = await client.post(
        f"{CONTROLLER}/internal/worker/claim",
        headers=HEADERS,
        json={
            "worker_id": WORKER_ID,
            "pool": WORKER_POOL,
            "slots": WORKER_SLOTS,
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
            f"pool={WORKER_POOL} slots={WORKER_SLOTS}",
            flush=True,
        )
        heartbeat_due = 0.0
        loop = asyncio.get_running_loop()

        while True:
            try:
                now = loop.time()
                if now >= heartbeat_due:
                    await heartbeat(client)
                    heartbeat_due = now + 10.0

                if await local_busy(client):
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
