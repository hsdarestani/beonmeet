# BeOnMeet paid launch readiness — 2026-11-13

## Pricing approved for implementation

| Plan | Monthly price (IRR equivalent in toman) | Recording allocation | Period |
|---|---:|---:|---|
| Basic | 298,000 toman | 120 minutes | 30 days |
| Pro | 498,000 toman | 360 minutes | 30 days |
| Business | 998,000 toman | 900 minutes | 30 days |

Source of truth: `app/billing_policy.py`. Legacy 1/3/6-month purchases and entitlements are preserved but no longer shown in new purchase offers. This is a **one-time purchase lasting 30 days**; the code does not implement automatic recurring charges.

**Important billing behavior:** current subscription renewals are queued after an existing active period. Switching tiers early requires support; an automatic prorated upgrade/credit workflow is not available. The current system blocks *new* recordings after recorded quota is exhausted, and reserves one hour per already queued/active paid recording to limit overlapping overspend. Existing sessions are allowed to finish and can exceed the remaining allowance. **No automatic extra-hours charging** is implemented. The marketing and terms must never promise a hard cut-off of an in-progress recording.

**Existing free policy:** 5 free recordings over the lifetime of a user, up to the recorder's global per-meeting maximum. This is an abuse/cost risk for broad advertising until validated.

## Non-negotiable go/no-go checks before purchased traffic

- [ ] Confirm the actual upgraded host CPU, memory, shared CPU fair-use policy, available disk, memory-backed recording storage, swap, networking and separate duties of the shared VPS. A hardware resize alone does not increase the deployed recorder's `MAX_CONCURRENT_MEETINGS`.
- [ ] Verify live `GET /health`: `max_concurrent_meetings`, `healthy_free_workers`, `healthy_premium_workers`, `transcription_concurrency`, `pending_delivery_jobs`, `database_backend`, `autoscaler_enabled`. Resolve any stale single-recorder mode before promoting concurrency.
- [ ] Ensure `TELEGRAM_BOT_URL=https://t.me/<verified_username>` is set in production. It must match Telegram `getMe`; without it the landing page falls back to contact email instead of a purchase CTA.
- [ ] Safely back up database, OAuth token files, persistent controller state and existing container configuration; verify ability to restore. Never publish or commit secrets.
- [ ] Verify the exact deployed commit and migrations against a staging database before production. Current deploy workflow is **manual** and asserts a `BEONMEET_STAGING_NO_POLL=1`, `AUTOSCALE_ENABLED=false`, idle single-worker runtime. Do not bypass its guardrails without a documented migration and QA of the shared server.
- [ ] Test Basic/Pro/Business payment intent, correct price/plan on HamoonCloud, Zibal test payment, server-side payment verification, idempotent callback, subscription activation and Telegram confirmation. Never charge real customers in unverified conditions.
- [ ] Test 1/2/4/6/8/12 simultaneous real Google Meet joins, both free and paid queues, worker crashes, rejected admissions, account challenges, queue expiration and 60+ minute recording; determine realistic `MAX_CONCURRENT` using CPU/RAM/swap/recording success and delivery latency, not a YAML slot count.
- [ ] Test paid quota expiration, exhausted balance, queued and concurrent request, manual `/now`, Calendar auto-join, renewal within an active period and already-paid legacy user. Confirm no unpaid recording can consume the paid-only capacity.
- [ ] Test full Telegram delivery of video/audio/transcript on a 5-minute, 1-hour, 3-hour recording (including chunking over Telegram upload limits), failed upload and idempotent delivery recovery. Check `/dev/shm` and expiry/cleanup.
- [ ] Verify all public offer prices, plan descriptions, /plans in Persian/English/German, /privacy, /terms, the Telegram landing CTA and mobile page. Check user notice/participant consent in ad copy.
- [ ] Implement metrics and alarms: join failure rate, unadmitted rate, pending delivery backlog, recorder free slots, session overrun, quota accuracy, memory/disk utilization, payment activation failures and support response process. Start with a small controlled campaign and stop automatically/manual if error rates rise.
- [ ] Confirm business/legal readiness for the actual service region (privacy controller identity, support contact, refund/cancellation information and meeting recording consent requirements). The existing generic contact address alone may be insufficient.

## Deployment policy

The GitHub branch here is a proposed code change, **not proof of production release**. Make the read-only live checks, run CI, perform a staging rollout, and then follow the existing manual deploy process for the verified runtime. Because multiple services share the VPS, do not force-enable Docker Compose autoscaling or rebuild Chrome containers blindly.

## Customer-facing claims

Safe: scheduled Google Meet recording, delivery to Telegram, support for separate audio/transcription when successfully processed, up to the paid plan's monthly recording-hour allowance.

Not yet safe: unlimited recording, guaranteed join to every event, guaranteed simultaneous sessions, no human approval by Meet hosts, automatic top-ups, instantaneous upgrades, or unbounded capacity.
