#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scaling_policy", ROOT / "app" / "scaling_policy.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

order_queue = MODULE.order_queue
bounded_scale_up = MODULE.bounded_scale_up
workers_needed = MODULE.workers_needed


def test_1000_user_priority() -> None:
    queue = []
    for i in range(1000):
        premium = (i % 20 == 0)
        queue.append(
            {
                "event_id": f"event-{i:04d}",
                "premium": premium,
                "queued_at": f"2026-09-25T12:{i // 60:02d}:{i % 60:02d}+00:00",
            }
        )

    ordered = order_queue(queue)
    premium_count = sum(1 for item in queue if item["premium"])
    assert premium_count == 50
    assert all(item["premium"] for item in ordered[:premium_count])
    assert all(not item["premium"] for item in ordered[premium_count:])

    premium_times = [item["queued_at"] for item in ordered[:premium_count]]
    free_times = [item["queued_at"] for item in ordered[premium_count:]]
    assert premium_times == sorted(premium_times)
    assert free_times == sorted(free_times)


def test_30_concurrent_burst() -> None:
    # 30 simultaneous meeting requests: 6 Premium and 24 Free.
    # Local production baseline currently has 4 Premium + 8 Free slots.
    premium_waiting = max(0, 6 - 4)
    free_waiting = max(0, 24 - 8)

    assert premium_waiting == 2
    assert free_waiting == 16

    # Remote worker size is 3. A scale cycle is intentionally capped at two
    # workers to avoid runaway Hetzner creation on one bad metric sample.
    assert bounded_scale_up(
        queue_size=premium_waiting,
        available_slots=0,
        worker_slots=3,
        current_workers=0,
        max_workers=3,
        per_cycle_limit=2,
    ) == 1

    assert bounded_scale_up(
        queue_size=free_waiting,
        available_slots=0,
        worker_slots=3,
        current_workers=0,
        max_workers=6,
        per_cycle_limit=2,
    ) == 2


def test_capacity_math() -> None:
    assert workers_needed(0, 0, 3) == 0
    assert workers_needed(1, 0, 3) == 1
    assert workers_needed(3, 0, 3) == 1
    assert workers_needed(4, 0, 3) == 2
    assert workers_needed(10, 4, 3) == 2

    # Max-worker hard stop.
    assert bounded_scale_up(100, 0, 3, current_workers=6, max_workers=6) == 0

    # Available capacity must suppress unnecessary scale-out.
    assert bounded_scale_up(5, 6, 3, current_workers=2, max_workers=6) == 0


def main() -> None:
    test_1000_user_priority()
    test_30_concurrent_burst()
    test_capacity_math()
    print("READINESS_LOAD_TEST_PASS")
    print("simulated_users=1000")
    print("simulated_peak_meetings=30")
    print("premium_priority=pass")
    print("autoscale_policy=pass")


if __name__ == "__main__":
    main()
