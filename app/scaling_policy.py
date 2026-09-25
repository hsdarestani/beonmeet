from __future__ import annotations

import math
from typing import Any


def order_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Premium first, then FIFO within each tier."""
    return sorted(
        list(items),
        key=lambda item: (
            0 if bool(item.get("premium")) else 1,
            str(item.get("queued_at") or ""),
        ),
    )


def workers_needed(queue_size: int, available_slots: int, worker_slots: int) -> int:
    queue_size = max(0, int(queue_size))
    available_slots = max(0, int(available_slots))
    worker_slots = max(1, int(worker_slots))
    missing = max(0, queue_size - available_slots)
    return math.ceil(missing / worker_slots) if missing else 0


def bounded_scale_up(
    queue_size: int,
    available_slots: int,
    worker_slots: int,
    current_workers: int,
    max_workers: int,
    per_cycle_limit: int = 2,
) -> int:
    need = workers_needed(queue_size, available_slots, worker_slots)
    room = max(0, int(max_workers) - max(0, int(current_workers)))
    return max(0, min(room, need, max(1, int(per_cycle_limit))))
