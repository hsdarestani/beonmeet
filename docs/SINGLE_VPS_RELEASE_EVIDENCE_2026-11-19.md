# Single-VPS BeOnMeet release evidence — 19 November 2026

**Result: successful isolated controller release; no server upgrade purchased.**

The one-shot GitHub Actions deployment [run 44483284268](https://github.com/hsdarestani/beonmeet/actions/runs/44483284268) verified recorder idle; backed up controller app files, environment, SQLite DB and state; confirmed Telegram bot username; installed the four reviewed application files from commit `1e6319bd41d848d75c1659074640aa0b02d8f906`; restarted only `beonmeet-controller`; and passed the localhost health, Persian plan landing-page, Telegram CTA, public HTTPS page, nginx configuration and shared-host unrelated-service checks.

Backup on the existing VPS: `/opt/beonmeet/.launch-backup-20261119T075512`. Do not delete until real payment and recording regression tests pass. The first attempt was automatically rolled back due to the old Docker-only hardcoded `/data` path; the corrected version respects `BEONMEET_DATA_DIR`. Regression test now guards this systemd compatibility.

A read-only [post-release verification run 44483624834](https://github.com/hsdarestani/beonmeet/actions/runs/44483624834) confirmed:

| Setting | Verified live value |
|---|---|
| Plans shown in Persian landing page | Basic 298,000, Pro 498,000, Business 998,000 toman |
| Telegram bot destination | https://t.me/BeOnMEETbot |
| New paid sales allowed for all three tiers | Yes (active paid subscribers=0 at audit) |
| Active paid-user capacity cap | 12 |
| Total advertised paid-hour sales cap | 60h |
| Free trial | One recording (lifetime) |
| Recording capacity | One local recorder only |
| Server autoscale | Disabled |
| Transcription model | small |
| Whisper CPU threads | 2 |
| Concurrent transcription jobs | 1 |
| Admin copies of recordings | Disabled |
| Host machine | 3 vCPU, ~6 GiB RAM, ~30 GB disk |

No new VPS or Docker recorder was created. No production payments or real Google Meet recordings were created or consumed in this verification. Files and live service remained on the original host.

## Not yet proven and therefore still launch risks

- A real paid checkout and verified payment callback through HamoonCloud/Zibal for each of the three new plan IDs.
- A user-authorized Google Meet recording end-to-end, including admission, Telegram delivery, MP3, transcription and quota decrement.
- Operational stability under queued demand and concurrently arriving users, and actual capacity with CamCam on the shared host.
- Refund/cancellation support workflow, billing disclosures and applicable recording-consent requirements.

**Recommendation:** run a small controlled QA checkout and Meet recording before any broad paid advertisement. Do not promise instantaneous recording or simultaneous joins. Keep the one-time deployment CI step removed so future PR edits cannot restart the live service.
