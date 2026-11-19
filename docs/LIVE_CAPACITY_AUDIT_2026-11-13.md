# Live BeOnMeet read-only capacity audit — 2026-11-13

**Status: BLOCKED FOR PAID ADVERTISING.** The deployed host is not the presumed upgraded recording host and has not been validated for multi-session paid production. Do not change advertising to new price tiers until post-deployment live checks pass.

Source: GitHub Actions [run 43410871824](https://github.com/hsdarestani/beonmeet/actions/runs/43410871824), job `production-readonly-capacity-audit`. Read-only SSH to the existing host and JSON inspection of `http://127.0.0.1:8109/health`. No production files or processes were changed.

| Observable | Verified result |
|---|---|
| Visible CPU | 3 vCPU |
| Memory | 5.79 GiB total; ~3.71 GiB available during audit |
| Root disk | 29.42 GiB total, ~8.98 GiB available |
| Host /dev/shm | 2.89 GiB total / free |
| BeOnMeet controller | active |
| Deployed repository commit | `29239e32a520` (short SHA) |
| Current recording concurrency | **1 total** |
| Free slots / reserved Premium slots | 1 / 0 |
| Free / Premium queues | 0 / 0 at audit |
| Actual autoscaling | disabled |
| Remote workers | 0 |
| Transcription concurrency | 1 |
| Backend database | SQLite |
| Delivery backlog | 0 at audit |
| Production `AUTOSCALE_ENABLED` flag | false |
| Production `BEONMEET_STAGING_NO_POLL` flag | 0 |

The repository's theoretical Docker Compose configuration for many worker slots **is not the deployed runtime**. Server upgrade claimed externally must be verified against the actual production endpoint; it may refer to a different machine or a different panel.

## Required next operational actions
1. Identify the intended upgraded server and confirm its IP, actual CPU, RAM, disk, /dev/shm, network quality and whether its host matches `beonmeet.smarbiz.sbs`. Do not migrate production without safe backup and tested rollback.
2. Adapt the currently pinned `ops/shared-vps-source-audit-20261022` deployed single-controller architecture before switching to multi-recorder production. Validate a separate test deployment for the new backend.
3. Run end-to-end payment and recording-hour quota tests on isolated staging and a real Google Meet test meeting. Exercise queues, Telegram uploads, large files, transcription, admin, user data retention and consent.
4. Configure the verified Telegram bot destination (`TELEGRAM_BOT_URL`) and verify it against Bot API `getMe`. Confirm verified payment provider amounts from its own endpoints.
5. Complete the go/no-go checklist in `docs/AD_LAUNCH_READINESS_2026-11-13.md`; only then merge and deploy the launch branch via a safe production release procedure.

This snapshot is not proof of any other machine's size or the contractual VPS plan. The temporary CI diagnostic step should not be kept in the codebase after this evidence is archived.
