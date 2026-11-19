# BeOnMeet — prepaid, non-expiring recording-hour wallet
**Release:** 19 November 2026  
**Live host:** existing shared VPS, 3 vCPU / 5.8 GiB RAM, alongside CamCam

## What customers buy

No monthly subscription and no time-limited recording plan is sold to new customers. Each one-time payment **immediately adds** the purchased number of recorded hours to a permanent, cumulative wallet.

| Amount of recording time | Price (toman) | Internal checkout code (kept for HamoonCloud compatibility only) |
|---|---:|---|
| 2 hours | 298,000 | basic |
| 6 hours | 498,000 | pro |
| 15 hours | 998,000 | business |

The quantity options are **credit denominations, not subscriptions**. All credits are measured in integer seconds. The balance can be viewed via the Telegram **⏱ شارژ ساعت ضبط** button or **/credits**; legacy /plans and /premium remain accepted as hidden compatibility aliases only. The public Telegram command list advertises /credits, not /plans, and the disabled /auto command remains hidden.

- Buying 2 hours twice instantly credits a combined 4 hours; no 30-day delay.
- 30 minutes of successful recording after those purchases leaves 3 hours 30 minutes.
- Credit does **not expire** and is not reset monthly. There is **no recurring charge**, no automatic renewal, and no automatic top-up.
- Each successfully delivered/completed recording deducts the actual recorded seconds once. Retries with the same recording filename do not deduct twice.
- An already-started meeting may exceed the remaining balance. A negative internal ledger balance represents that overrun, and future top-ups settle it first. No automatic extra payment is charged.
- Three sale quantities use **the existing approved prices**, avoiding the invention of a new per-hour price. A new 1-hour price or arbitrary hour quantity would require separate business pricing approval.
- The existing single-server maximum **12 active users / 60 outstanding sold hours** is retained. It is now based on unspent credit, not rolling 30-day subscriptions.

## Financial and historical safeguards

- New `credit_entries` ledger: unique reference, Telegram account, signed seconds, transaction kind, timestamp. Verified Zibal payment receipts use `zibal:<receipt>`, recorded outputs use `recording:<chat>:<filename>`; both are idempotent, with ownership/amount consistency checks. Credentials are not logged.
- The old `basic`, `pro`, `business` **internal** payment codes remain supported by HamoonCloud, so its recently fixed plan-code validation does not need another change. Customer-visible labels all say “buy recording hours”, not “plan”.
- Migration on startup converts each still-active paid 30-day plan's unspent allowance into wallet credit; any already-paid *future* periods become fully usable credit immediately. Past expired hours do not revive. Ledger migration refs `migration:subscription:<id>` stop double migration after restart.
- Historical purchase/subscription tables and receipts are preserved. Grandfathered legacy unlimited subscribers (`monthly/quarterly/halfyear`) keep their preexisting entitlements until the original expiry, without consuming independently purchased wallet credits during that period.
- The administrator can manually add 2/6/15 hours to the same wallet; account revocation can remove remaining credit via a ledger entry without deleting history.

## Customer surfaces

- Telegram: translated FA/EN/DE help and purchase descriptions, menu button, /credits status, verified-payment confirmation showing actual cumulative balance.
- Web: `/` and `/fa` landing pages, prices, no expiration, repeat purchases, and no subscription references to paid sales.
- Public `/terms` updated to cover non-expiring credit, debit of recorded time and handling of overruns.
- The unverified “All Meetings” feature remains disabled and not advertised.

## Evidence, backup and rollout

- Source/production audit: [Actions #44517246520](https://github.com/hsdarestani/beonmeet/actions/runs/44517246520). All four live Python source files matched the reviewed base commit exactly; old active prepaid periods = 0; active old unlimited subscriptions = 0; nonexpired pending payment intents = 0; no credit ledger yet. Controller and both workers idle, CamCam healthy.
- CI regressions include actual SQLite wallet behavior: consecutive 2-hour purchases add 4 hours, duplicate receipt does not add again, successful file deducts once, excess recording time subtracts from future top-up, original legacy rights preserved, current/future paid periods migrate only once.
- Protected production rollout: [Actions #44517964668](https://github.com/hsdarestani/beonmeet/actions/runs/44517964668). Confirmed idle queue/recording/delivery jobs, backed up original SQLite DB and app/env/state, installed only the five BeOnMeet app files, restarted controller only. All 5 recording slots, nginx, public landing pages and monitored CamCam containers remained healthy.
- Telegram API `getMyCommands` confirmed **/credits shown**, /plans and /auto omitted, in FA/EN/DE.
- Exact protected backup: `/opt/beonmeet/.prepaid-wallet-backup-20261119T114752`
- Live wallet schema initialized with **0 rows**. This is expected because the production audit confirmed no still-active public subscriptions or new verified payments.
- Temporary production SSH workflow was removed after release. The deployment script is retained under `scripts/deploy_prepaid_hour_wallet.sh`, but is intentionally one-shot and refuses repeat execution without review.

## Outstanding items before taking payments or paid ads

**Zibal result 115** currently rejects the same VPS outbound IP `143.20.60.195` for the merchant. This is an external payment-provider allowlist setting, not a wallet-code error. The merchant owner must approve the IP in Zibal's gateway general settings / ask support, and only then run a small, authorized real payment and verify that the receipt increases wallet seconds. This release did **not** charge any money or confirm a real payment end to end. Also do not advertise guaranteed five simultaneous real Google Meet recordings until a five-room end-to-end consented test passes; the 4-minute 5-stream synthetic AV load test did not test live Meet admission.

**Campaign status:** no-go for taking paid purchases until Zibal IP authorization and a verified real top-up; the code is live and internal wallet tests pass.
