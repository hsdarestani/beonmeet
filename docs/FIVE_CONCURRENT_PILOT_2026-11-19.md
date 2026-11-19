# BeOnMeet — five simultaneous-slot experimental release
**Date:** 2026-11-19  
**Host:** Existing shared VPS (3 vCPU, ~5.8 GiB RAM, 30 GiB root storage), shared with CamCam. No additional VPS provisioned.

## Exactly what has been validated

1. GitHub Actions [isolated synthetic test #44487761613](https://github.com/hsdarestani/beonmeet/actions/runs/44487761613) successfully captured **five independent 640×360 VP8 canvas streams concurrently for 12 seconds**. All five files produced nonzero data; measured synthetic Chrome load peaked about 121% of one CPU and memory about 0.54 GiB. This is *not* a Google Meet workload and had no meeting audio.
2. Pinned compiled worker audiofix image accepted the deterministic low-resource VP8 overlay and passed `node --check` in an isolated container.
3. [Controlled same-host release #44489575098](https://github.com/hsdarestani/beonmeet/actions/runs/44489575098) completed successfully. Health showed:
   - Controller `max_concurrent_meetings=5` and `local_free_meeting_slots=5`.
   - New worker `availableSlots=5`; no job was running during cutover.
   - Production `AUTOSCALE_ENABLED=false`; no new cloud server.
   - All CamCam API/pet/archive/petarchive health checks passed both before and after.
4. [Postrelease verification #44489711274](https://github.com/hsdarestani/beonmeet/actions/runs/44489711274) confirmed the live five-slot worker and controller are healthy. At that idle snapshot the host had about 3.9 GiB memory available; new worker consumed ~120 MiB RAM and Chrome ~763 MiB RAM.

## Resource allocation and implementation

- **Keep original worker:** `beonmeet-worker-single` still listens on localhost port 9124, configured one slot, untouched.
- **Experimental worker:** `beonmeet-worker-five` listens on localhost port 9126, `MAX_CONCURRENT_MEETINGS=5`. Limits: 1,150 MiB memory / 0.8 CPU.
- **Shared existing Chrome:** `beonmeet-chrome-single`; tuned live via cgroup to 2,350 MiB memory / 1.45 CPU. The Chrome image, login profile and process are not replaced.
- **Low-bitrate overlay:** `patches/patch_low_resource_compiled_recorder.py`; prefer VP8+Opus, request 640×360 pixels at ~8 fps, video bitrate 320 kb/s and audio 64 kb/s. Browser track constraints are best effort; some environments may retain higher source resolution and thus use more resources.
- **Controller:** points free and premium worker URLs to localhost 9126, `FREE_MEETING_SLOTS=5`, `PREMIUM_MEETING_SLOTS=0`, autoscaling off. Paid queue priority is preserved but there is **no physically reserved paid slot** because this is one shared pool.
- **Backup/rollback:** Root-owned backup `/opt/beonmeet/.five-slot-pilot-backup-20261119T084038`, immutable original worker is available; `scripts/rollback_five_on_shared_vps.sh` is idle-only and restores original controller env+one-slot runtime without deleting CamCam data.
- **No plan changes:** Basic 298k/2h, Pro 498k/6h, Business 998k/15h, one free trial, active paid subscriber cap 12, sold paid hours cap 60 remain as set.

## What is NOT verified

**Five actual simultaneous Google Meet recordings have not yet been proven.** No five real Google Meet rooms, browser admission flows, mixed speakers, video and audio delivery, transcription correctness, final Telegram files or meeting-duration quota metering were executed. The synthetic test does not exercise Google decoding, screen/tab capture permission, background capture, tab selection, audio, meeting admission or multi-hour sessions. The system may underperform or lose some recordings if 5 real meetings create too much CPU pressure or Chrome exceeds its cgroup memory/shm. The original Chrome container's 256-MiB internal shared-memory setting remains unchanged.

A 5-slot configuration is a **limit/eligibility, not an SLA**. Do not claim reliable five-meeting recording in paid advertisements before an approved five-room QA session completes (including random assignment of different meeting screen+audio content to prove correct separation), file delivery, CPU/RAM/IO observations and 20+ minutes stability. If testing fails, use `scripts/rollback_five_on_shared_vps.sh` when idle, or redesign the capture path instead of buying a server without user approval.

## Operational checks before high-traffic ads

- Test five separate Google Meet rooms at the same time, with host admission and participant consent, and inspect videos and transcripts individually for cross-meeting contamination.
- Monitor live `/health`, worker `/capacity`, node/chrome CPU throttling, memory pressure, /dev/shm free space, success/failure and postprocessing backlog.
- Keep CamCam API/pet/archive/petarchive green and compare traffic during peak use.
- Test real Zibal/HamoonCloud checkout and billing quota change in a controlled approved transaction.
- Never enable automatic Hetzner scaling on this small VPS.

The one-time rollout workflow job has been removed from CI. The follow-up PR should include code and evidence only, not a recurring remote SSH deployment action.
