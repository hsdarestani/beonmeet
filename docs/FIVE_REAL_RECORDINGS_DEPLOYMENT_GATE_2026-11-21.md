# BeOnMeet — Five REAL concurrent Google Meet recordings, production gate

Date: 2026-11-21. Status: **BLOCKED FOR FIVE-ROOM SLA**. The product currently has one shared authenticated Google Chrome instance. Do not raise `SHARED_CHROME_MAX_ACTIVE` above 1 on the current host, and do not claim five real meetings are verified.

## Evidence from read-only live production
- Audit: https://github.com/hsdarestani/beonmeet/actions/runs/44931195096
- 3 vCPU, 5926 MiB total memory; 8.52 GiB disk free when sampled, sharing host with CamCam.
- The sole local active worker on port 9126 advertises `maxConcurrentJobs=5`, but has `GOOGLE_CHROME_CDP_URL=http://beonmeet-chrome-single:9223`; the old fallback worker on port 9124 points to the **same** browser.
- Controller `SHARED_CHROME_MAX_ACTIVE=1` (default, correctly fail-closed), with both free/premium URLs pointing to the five-slot worker. Only one real browser path exists.
- One real recording was active and one premium user was queued during initial audit; 480p synthetic test aborted before starting because of that real queue: https://github.com/hsdarestani/beonmeet/actions/runs/44931078086 .
- `AUTOSCALE_ENABLED=false`, `HETZNER_API_TOKEN` absent and no prebuilt image bundle. No remote worker has been installed/validated by this work.
- Prior synthetic 5x360p AV encoding run on Nov 19 passed once, failed once, and does **not** establish 5 true Meet captures or uploads.

## Production implementation required
1. **Dedicated recorder capacity**: Provision a recording-only host or independent recording hosts. Working sizing starting point for five simultaneous 480p sessions: 8 dedicated or adequately guaranteed vCPUs, 16 GiB RAM, fast disk with sufficient temporary upload capacity; final size must be adjusted from measured real Google Meet loads. This is not an assertion that this size is enough under all conditions. Keep the existing BeOnMeet controller and CamCam untouched.
2. **Five independently operating worker + browser pairs**: Each real slot gets its own Chrome CDP instance, separate profile/user data directory, independent worker process limited to **one** running job, dedicated recording temporary directory, and preferably distinct authenticated recorder Google identities. Never point two simultaneously scheduled workers at the same Chrome CDP instance. Existing `worker/agent.py` supports outbound HTTPS heartbeats/claims, so recorder nodes do not need public incoming worker endpoints. Set unique `WORKER_ID` for every agent, `WORKER_SLOTS=1`, and the appropriate `WORKER_POOL` per lane. Remote agents use the controller's `/internal/worker/heartbeat`, `/internal/worker/claim`, and `/internal/worker/accepted` paths.
3. **Use identical approved deployed recorder code**: Reproduce the current production compiled Google Meet overlay, including `GOOGLE_MEET_TRUSTED_JOIN_PATCH`, `BEONMEET_MODERN_IN_CALL_PROOF_V1`, and `BEONMEET_BROWSER_QUALITY_ARG_V1`, along with browser authentication and recording upload fixes. Do not deploy the unpatched upstream worker image, even if it passes a /capacity check. Keep signed-in profiles and INTERNAL_SECRET out of Git history and workflow logs.
4. **Runtime gate**: `SHARED_CHROME_MAX_ACTIVE=1` is correct per isolated local Chrome; remote agents should each also be limited to one job. One-slot-per-physical-Chrome is essential. Add only verified healthy workers to serving capacity; return queued state if not all five are ready. The local 5-slot worker is **not** an independent additional 5 slots.
5. **Five-room acceptance**: Start five separately hosted Google Meet sessions with consent, test mixed Open/Trusted joins and admission, verify five `recording-started` callbacks, five distinct AV files with scene-specific audio and video, stable ≥20-minute capture, all five deliveries, proper quota accounting (no charge for failed attempts), no swapped audio, and no reboot. Observe CPU throttling, Chrome memory/OOM, encoder errors, host RAM/swap/disk/network, and CamCam health throughout.
6. **Fail closed**: Only after a clean full-real five-room E2E run may the service advertise five reliable simultaneous recordings. Preserve original one-slot rollout fallback and perform a live-traffic-safe cutover when all active jobs/delivery queues have drained. Keep queue capacity behavior for a sixth simultaneous request.

## Software validation
`tests/five_isolated_workers_dispatch_test.py` invokes the real controller dispatch functions with 5 different one-slot worker URLs. It confirms five requests are accepted concurrently and a sixth queues. This **does not prove any real additional hardware or five live Google Meet recordings**.

## Current blocker
No accessible Hetzner server-creation API token, no provisioned isolated Chrome workers, and no five consented test meetings. There is no responsible way to remove the single-browser safety gate on the existing CamCam-shared 3-vCPU VPS and claim five reliable real recordings.
