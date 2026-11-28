import json
import os
import time
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
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False, separators=(",", ":"))
            fp.flush()
            os.fsync(fp.fileno())
        tmp.replace(self.fallback_file)
        directory = os.open(self.fallback_file.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def load(self) -> tuple[dict[str, Any] | None, str]:
        file_state = self._read_file()
        try:
            raw = self.redis.get(STATE_KEY)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    # Redis may recover with an older value after a temporary
                    # outage during which the fsynced mirror accepted jobs.
                    if file_state and int(file_state.get("_saved_at_ns") or 0) > int(data.get("_saved_at_ns") or 0):
                        self.redis.set(STATE_KEY, json.dumps(file_state, ensure_ascii=False))
                        return file_state, "file"
                    return data, "redis"
        except Exception as exc:
            print("redis state load failed:", repr(exc), flush=True)

        if file_state is not None:
            # Best-effort migration back into Redis.
            try:
                self.redis.set(STATE_KEY, json.dumps(file_state, ensure_ascii=False))
            except Exception:
                pass
            return file_state, "file"

        return None, "empty"

    def save(self, state: dict[str, Any]) -> None:
        state = {**state, "_saved_at_ns": time.time_ns()}
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        redis_ok = False
        try:
            self.redis.set(STATE_KEY, payload)
            redis_ok = True
        except Exception as exc:
            print("redis state save failed:", repr(exc), flush=True)

        # Always keep the old file as a safety mirror. It is tiny metadata only;
        # recordings are never stored here.
        mirror_ok = False
        try:
            self._write_file(state)
            mirror_ok = True
        except Exception as exc:
            print("state mirror save failed:", repr(exc), flush=True)

        if not redis_ok and not mirror_ok:
            raise OSError("Could not persist controller state in Redis or local mirror")

    def ping(self) -> bool:
        try:
            return bool(self.redis.ping())
        except Exception:
            return False
