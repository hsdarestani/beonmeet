# BeOnMeet — Five independent local recorder lanes (2026-11-22)

## Goal and production boundary
Same upgraded ParsVDS VPS (23.47 GiB RAM, **7** detected vCPUs, 118G root filesystem) hosts BeOnMeet and CamCam. No purchase of extra servers, no change to recording method, no interruption of live customer sessions. Final SLA requested: five simultaneous **real** Google Meet video+audio recordings for at least 60 minutes. Nothing in a synthetic stress test alone satisfies this SLA.

## Current staged topology
- Original authenticated Chrome: `beonmeet-chrome-single`; original production recorder `beonmeet-worker-five` at `127.0.0.1:9126`, advertises 5 internal slots but remains **serialized to 1** by controller `SHARED_CHROME_MAX_ACTIVE=1`.
- New Chrome CDP instances: `beonmeet-isolated-chrome-2` through `-5`, each with its own **exclusive** writable profile clone at `/opt/beonmeet/chrome-profile-isolated-N` and its own bounded cgroup.
- New one-job recorder processes: `beonmeet-isolated-worker-2` through `-5` on localhost ports `9132` to `9135`. Each worker's `GOOGLE_CHROME_CDP_URL` points at exactly one corresponding Chrome; `MAX_CONCURRENT_MEETINGS=1`.
- The four new workers use the **same deployed patched GoogleMeetBot compiled file** as the current production worker. Do not replace them with upstream unpatched images.
- `/dev/shm/beonmeet` is the shared recording spool; individual capture filenames and per-request IDs remain unique. Profiles are not shared writable. Extra Chrome VNC ports bind localhost only.
- The original Chrome and worker are preserved as the rollback route. Staged workers do not receive production jobs until a guarded cutover changes controller `.env`.
- `/opt/beonmeet/.five-isolated-runtime` stores the protected per-lane worker environment files; never commit or print them.

## Confirmed acceptance so far
1. Staging: GitHub run [45004438491](https://github.com/hsdarestani/beonmeet/actions/runs/45004438491) — 4 new Chrome+Worker pairs started, each reported 1/1 available; original controller and CamCam remained healthy.
2. Google profile markers: run [45004577384](https://github.com/hsdarestani/beonmeet/actions/runs/45004577384) — authenticated Google cookie markers present in all 4 independent Chrome profiles (not a complete Google login guarantee).
3. Synthetic 5-way AV: run [45004828615](https://github.com/hsdarestani/beonmeet/actions/runs/45004828615) — five isolated Chrome instances simultaneously captured 480p/10fps VP8+Opus for 360+ seconds; 5/5 valid files and individually verified audio frequencies, with 0 MediaRecorder errors, CamCam unaffected.
4. Actual Meet link creation without calendar edits or invitations: runs [45005421369](https://github.com/hsdarestani/beonmeet/actions/runs/45005421369) and [45005589412](https://github.com/hsdarestani/beonmeet/actions/runs/45005589412) — five unique private QA room URLs created and stored 0600 on server.
5. One real Meet test: run [45005769135](https://github.com/hsdarestani/beonmeet/actions/runs/45005769135) — worker accepted real join, entered call and invoked recording-started callback, then emitted an upload callback around 4 minutes later. **File AV acceptance failed and requires diagnosis; do not claim completion.**
6. 720p/15fps test and five REAL concurrent room acceptance are separate gates, not interchangeable with 480p synthetic.

## Cutover gate — never promote merely because /capacity says 5
The guarded script `scripts/cutover_five_isolated_local_workers.py` checks that all 5 endpoints are reachable, new workers are one-slot, production has no running jobs/queues/deliveries, CamCam healthy, and active Chrome guard stays at 1 **per endpoint**. It atomically backs up/replaces .env, restarts the controller, checks 5 endpoints and healthy workers, and rolls back .env on failure. Only invoke after passing real Meet join/recording acceptance and with an idle production service.

Post-cutover `FREE_WORKER_URLS` and `PREMIUM_WORKER_URLS` should point at `9126,9132,9133,9134,9135`; `SHARED_CHROME_MAX_ACTIVE=1`. This is a 5-way single-session-per-browser architecture, **not** a shared Chrome configured for 5.

## Outstanding work before guaranteeing 60 minutes
- Verify nonempty, playable audio and video output after real Google Meet join (not only a callback).
- Verify five distinct real Google Meet rooms run simultaneously, including an admission test where needed and 5 separate output files.
- Sustained 60-minute end-to-end run with consent and actual audio/video from other participants, plus delivery, quota accounting, recorder restart/recovery, CPU throttling, disk, and CamCam observation.
- Review identical Google account use across the 5 cloned profiles; authenticated cookies do not prove concurrent Meet permissions.
- Evaluate 720p video quality at a measurable sustainable codec/bitrate before calling it high-quality.

## Production protection
All test callbacks go to Docker-private QA sink containers. Do **not** write fake jobs into billing, do not send QA videos to Telegram users, do not change CamCam services and do not disable single-Chrome guard on unverified production.
