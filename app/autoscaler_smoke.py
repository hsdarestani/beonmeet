import asyncio
import json
import os
import sys
import time

import httpx

from hetzner_autoscaler import (
    _create_server,
    _delete_server,
    _list_servers,
    _runtime,
    _server_worker_id,
    enabled,
)


async def run() -> int:
    if not enabled():
        print("AUTOSCALER_SMOKE_FAIL: autoscaler is not enabled")
        return 2

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        existing = await _list_servers(client)
        server = await _create_server(client, "free", existing)
        server_id = int(server.get("id") or 0)
        worker_id = _server_worker_id(server)
        if not server_id or not worker_id:
            print("AUTOSCALER_SMOKE_FAIL: Hetzner server creation returned no id/worker")
            return 3

        print(
            "AUTOSCALER_SMOKE_CREATED "
            + json.dumps(
                {
                    "server_id": server_id,
                    "worker_id": worker_id,
                    "server_type": server.get("server_type", {}).get("name"),
                    "status": server.get("status"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        started = time.monotonic()
        deadline = started + int(os.environ.get("AUTOSCALER_SMOKE_TIMEOUT_SECONDS", "900"))

        try:
            while time.monotonic() < deadline:
                runtime = _runtime(worker_id)
                if runtime:
                    available = int(runtime.get("available_slots") or 0)
                    max_jobs = int(runtime.get("max_jobs") or runtime.get("slots") or 0)
                    if max_jobs > 0 and available > 0:
                        elapsed = int(time.monotonic() - started)
                        print(
                            "AUTOSCALER_SMOKE_READY "
                            + json.dumps(
                                {
                                    "worker_id": worker_id,
                                    "elapsed_seconds": elapsed,
                                    "runtime": runtime,
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        return 0
                await asyncio.sleep(10)

            print(
                f"AUTOSCALER_SMOKE_FAIL: worker {worker_id} did not heartbeat ready before timeout",
                flush=True,
            )
            return 4
        finally:
            try:
                await _delete_server(client, server_id)
                print(f"AUTOSCALER_SMOKE_DELETED server_id={server_id}", flush=True)
            except Exception as exc:
                print(f"AUTOSCALER_SMOKE_DELETE_ERROR: {exc!r}", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
