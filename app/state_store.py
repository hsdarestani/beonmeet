import json
import os
from pathlib import Path
from typing import Any

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
STATE_KEY = os.environ.get("REDIS_STATE_KEY", "beonmeet:controller:state")


class DurableStateStore:
    """Redis-first controller state with a local JSON safety mirror.

    Redis is the source of truth for the live queue/state so recorder workers can
    scale independently. The JSON file remains only as a fallback/migration copy,
    which keeps current installations recoverable if Redis is temporarily down.
    """

    def __init__(self, fallback_file: Path):
        self.fallback_file = fallback_file
        self.redis = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
            health_check_interval=30,
        )

    def _read_file(self) -> dict[str, Any] | None:
        if not self.fallback_file.exists():
            return None
        try:
            data = json.loads(self.fallback_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_file(self, state: dict[str, Any]) -> None:
        self.fallback_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fallback_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(self.fallback_file)

    def load(self) -> tuple[dict[str, Any] | None, str]:
        try:
            raw = self.redis.get(STATE_KEY)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data, "redis"
        except Exception as exc:
            print("redis state load failed:", repr(exc), flush=True)

        file_state = self._read_file()
        if file_state is not None:
            # Best-effort migration back into Redis.
            try:
                self.redis.set(STATE_KEY, json.dumps(file_state, ensure_ascii=False))
            except Exception:
                pass
            return file_state, "file"

        return None, "empty"

    def save(self, state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        redis_ok = False
        try:
            self.redis.set(STATE_KEY, payload)
            redis_ok = True
        except Exception as exc:
            print("redis state save failed:", repr(exc), flush=True)

        # Always keep the old file as a safety mirror. It is tiny metadata only;
        # recordings are never stored here.
        try:
            self._write_file(state)
        except Exception as exc:
            print("state mirror save failed:", repr(exc), flush=True)

        if not redis_ok:
            # File mirror already preserved the mutation, so controller behavior
            # remains backward compatible during a Redis outage.
            return

    def ping(self) -> bool:
        try:
            return bool(self.redis.ping())
        except Exception:
            return False
