# BeOnMeet — affordable single-VPS launch, 19 November 2026

## Approved technical choice

Reuse the existing shared VPS (3 vCPU, ~6 GiB RAM, ~30 GiB root disk); **no new servers and no automatic Hetzner scaling**. Keep one active Chrome recorder; free and paid customers share it with paid queue priority, not a guaranteed dedicated slot. CamCam and all other services on the VPS must remain untouched.

## Paid plans (30-day one-time purchases)

| Plan | Monthly price | Included hours |
|---|---:|---:|
| Basic | 298,000 toman | 2 |
| Pro | 498,000 toman | 6 |
| Business | 998,000 toman | 15 |

The bot also offers **one free trial recording**, not five. Default availability guardrails for the small server are `PAID_SALES_MAX_ACTIVE_USERS=12` and `PAID_SALES_MAX_SOLD_HOURS=60`. An active paid subscription reserves its *full advertised hours*, so the cap may close sales even if some subscribers use less. Existing legacy unlimited plans reserve an estimated 15 hours each for this *sales gate only*; they are not silently converted to a capped plan. Existing subscribers are not billed again.

New offer/payment-intent creation is disabled when these limits are reached; old pending intents are supported. The sales gate rechecks active capacity before new checkout. Some race between purchase and fulfillment is still possible and must be monitored. Never refuse to activate an already verified payment due to later capacity changes.

## Compute and privacy guardrails

- `FREE_MEETING_SLOTS=1`, `PREMIUM_MEETING_SLOTS=0` — one recorder shared, paid-queue priority, not dedicated paid concurrency.
- `AUTOSCALE_ENABLED=false` — prevents surprise VPS bills.
- `TRANSCRIPTION_CONCURRENCY=1`, `WHISPER_MODEL=small`, `WHISPER_CPU_THREADS=2`, `RECOVERY_WHISPER_MODEL=base` — low-RAM CPU transcription at potentially lower accuracy than large-v3. Delivery/transcription can be slow during peaks.
- `SEND_ADMIN_RECORDING_COPIES=false` — customer files and transcripts are not copied to administrator by default; payment notifications can still be sent without user files.
- No forced-stop guarantee exactly at the included-hour boundary. Meter successfully completed recordings and block subsequent new joins when quota is used or already reserved by active/queued sessions.
- Keep persistent SQLite, state, Google OAuth tokens, Telegram sessions and Chrome profile intact.

## Scope of deployment

Use the 2026-11-19 reviewed code changes from PR #14 for `app/main.py`, `app/admin_panel.py`, `app/i18n.py`, `app/billing_policy.py`. Do **not** use `docker compose up --build`; this repository also contains a separate 16-vCPU/32GB theoretical topology that would overcommit the existing host.

The current production controller is a systemd service at port 8109 and a single recorder is on loopback port 9124. Before changing it: verify no recording/delivery/queue, back up .env/app/SQLite/state; check there are no unexpected edits to the target app files, and ensure an automatic rollback if startup or health checking fails.

Verify Telegram bot username via `getMe` and set only `TELEGRAM_BOT_URL`; never print its token. Check local and public /health and /fa. Test bot /plans, external checkout, paid callback, one admitted real Meet recording, premium delivery and backup recovery before sending paid traffic.

## Remaining limits for marketing

The single-queue recorder cannot promise immediate attendance at peak time. On a 3-vCPU machine a single recording plus transcription may already be CPU-heavy. Limited ads and waiting-list messaging are more realistic than scaling customer acquisition aggressively. Zero billed additional servers; actual server monthly cost remains the user's approx. 1 million toman, excluding network/processor fees and labor.

**No advertisement claiming guaranteed, unlimited, or multi-session recording until those features have actual test evidence.**
