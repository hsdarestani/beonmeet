# BeOnMeet payment issue — 19 November 2026

## Customer symptom

HamoonCloud shows in Persian: **«پرداخت قابل انجام نیست — درخواست منقضی یا نامعتبره؛ از داخل BeOnMeet دوباره تلاش کن»**.

## Confirmed root causes and live evidence

**Cause 1 (application bug, fixed):** BeOnMeet now creates 30-day plan codes `basic`, `pro`, `business` with prices 298,000, 498,000 and 998,000 toman. The on-host HamoonCloud source `/home/hamoondeploy/hamoon-source/external-payments.js` accepted only the retired `monthly`, `quarterly`, `halfyear` codes. Current legitimate payment intent returned **HTTP 200** from both internal `http://127.0.0.1:8109/api/billing/payment-intent` and external `https://beonmeet.smarbiz.sbs/api/billing/payment-intent`; the HamoonCloud start route returned **HTTP 409** with the customer's exact error.

- Evidence: read-only GitHub Actions diagnostic [run #44496438820](https://github.com/hsdarestani/beonmeet/actions/runs/44496438820).
- A rollback-guarded, **single-route plan allowlist patch** was applied on the shared VPS. It accepts old plan codes plus Basic/Pro/Business. It did **not** change the payment amounts, merchant key, CamCam handlers, or existing receipts. HamoonCloud restarted and responded to health probes.
- Deployment: GitHub Actions [run #44497434912](https://github.com/hsdarestani/beonmeet/actions/runs/44497434912), job `one-time-gateway-plan-fix`, successful. Backed up the original file under `/home/hamoondeploy/.payment-gateway-hotfix.w6tGRlBb/original-external-payments.js`.
- Code: `patches/fix_hamooncloud_beonmeet_plans.py` and `scripts/deploy_hamooncloud_payment_plan_fix.sh`, with regression `tests/hamooncloud_payment_patch_test.py`. The hotfix is idempotent; source is installed directly on the VPS because HamoonCloud's current deployed source tree does not have an in-place Git repo.

**Cause 2 (payment provider configuration, unresolved):** After accepting the updated plan, HamoonCloud's Zibal `/v1/request` returns **result 115: `invalid IP 143.20.60.195`**. Therefore the customer is no longer blocked by the plan validator but payment initiation still fails with HTTP **502**. This is **not fixed by code**. Do not submit advertising campaigns for paid subscriptions or claim checkout works until registered merchant IP is resolved and a real transaction is verified.

- Evidence: postpatch Zibal diagnostics [run #44497659207](https://github.com/hsdarestani/beonmeet/actions/runs/44497659207) showing `[BEONMEET_PAYMENT_START] {message:'invalid IP 143.20.60.195', result:115}`.
- Zibal official merchant guidance (public channel): Payment gateway → Settings gear → General settings → authorized IP addresses. The Zibal merchant account administrator must add/approve **143.20.60.195** to the allowed outbound IPs of the correct merchant, or open a support ticket quoting result `115` and the IP. Do not use an unapproved proxy or bypass its IP controls.
- Do not disclose the Zibal merchant secret, account password or tokens in a support ticket, logs or GitHub.
- After the IP is approved, create a **fresh** /plans link, verify HamoonCloud redirects to the payment page, then test a single controlled and authorized real payment with verified callback, Telegram subscription activation and correct minute allowance. A redirect alone does not prove paid activation.

## Safety and cleanup

- No user funds were charged by these diagnostic GET requests.
- Existing BeOnMeet paid `payment_intents` persisted (new ones pending during initial audit); no subscription was silently activated. Ancient pending requests with 30-minute TTL are genuinely expired.
- No unrelated CamCam service files, users or existing payment records were changed.
- A second run of the one-shot deployment failed its pre-apply exact-diff assertion because the patch was already present; it did not restart the service or roll back the successful patch. The deployment script was subsequently made idempotent.
- All temporary SSH diagnostic/deployment GitHub Actions jobs were **removed** from the CI workflow, preventing accidental further runs.

**Go/no-go for paid ads: NO-GO until the merchant-account IP allowlist is updated and end-to-end payment QA succeeds.** Five simultaneous real Meet recordings and Telegram delivery also remain separately unproven; do not conflate synthetic load tests with live Meet QA.
