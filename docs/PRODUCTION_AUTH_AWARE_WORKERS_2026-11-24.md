# BeOnMeet — production auth-aware recording lanes (24 November 2026)

## Incident

Five HTTP-healthy workers were routed to production, but only one Chrome retained an authorized Google Meet account session. The others showed Guest / Sign in / Ask to join. The controller's original `/health` and `/capacity` checks did not detect this. Requests could be accepted by an unauthorized Chrome, repeatedly fail Google Meet admission and produce no recording.

## Production mitigation

1. `scripts/probe_recorder_auth.js` opens only *pre-existing, privately stored test rooms* in idle, private Chrome profiles and detects true signed-in `Join now` without `Sign in`/guest mode. It never clicks Join or records media. No meeting URL, cookie, or account identity is logged.
2. `scripts/worker_auth_monitor.py` runs periodically from `beonmeet-auth-watch.timer`, writes an atomic per-worker JSON readiness file to `/opt/beonmeet/data/worker-auth-readiness.json`, and keeps timestamps. It **does not probe a worker with an active recording**.
3. Only when all five lanes are idle, an authenticated source exists, and a 30-minute recovery cooldown permits it, the watchdog may locally synchronize the existing authorized recorder session via `scripts/recover_google_recorder_sessions_from_healthy_lane.js` and verify all outcomes. This is best-effort; Google may still invalidate clones.
4. `app/main.py` uses the live, time-bounded auth status (max age 360s) with `WORKER_AUTH_GUARD_ENABLED=true` before sending `/google/join`. Unverified/guest/stale workers are skipped; all-unready cases use the durable queue. This is **fail closed** and does not deduct credit merely for not joining.
5. The public `/health` includes `auth_guard_enabled`, `authenticated_free_workers`, and `authenticated_premium_workers`. These can differ from `healthy_free_workers`, which only checks HTTP health.
6. Production was patched with backups of `app/main.py` and `.env` and an emergency rollback path without modifying CamCam services. Worker routing remains five distinct endpoints; the single-Chrome active guard remains 1 per worker.

## Evidence

- 2026-11-24 [production deployment](https://github.com/hsdarestani/beonmeet/actions/runs/45439772657) passed: initial watchdog recovery verified 5/5, controller restarted with auth guard enabled, all five endpoints connected, CamCam healthy, no active customer queue.
- [Unit tests](https://github.com/hsdarestani/beonmeet/actions/runs/45439094179) exercised stale/guest auth status rejection and five-way dispatch with failover.
- Source of the original failure: [read-only four-Chrome status](https://github.com/hsdarestani/beonmeet/actions/runs/45433065582) — one signed-in lane, three stale standby sessions; original Chrome was also guest.

## Boundaries / remaining acceptance

- Google session validity can change between the latest check and the actual Meet admission; the guard reduces repeated Guest dispatches but cannot guarantee Google admission.
- Cloning a single Google session into five independent browser profiles has already shown revocations; for guaranteed long-term five-lane availability, independent authorized Google accounts or an explicitly supported authorization model may be needed.
- A production five-real-meeting **60-minute** video+audio-and-delivery endurance run remains necessary; prior proof was one minute of overlapping real recording starts plus synthetic AV capture.
- Never claim a user recording succeeded until its file is delivered and media validated.
