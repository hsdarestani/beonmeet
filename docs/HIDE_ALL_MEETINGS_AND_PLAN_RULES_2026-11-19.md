# BeOnMeet — Hide unverified All Meetings and explain 30-day recording plans
**Production release:** 19 November 2026

## Decision and customer-facing outcome

The optional personal Google Calendar "All Meetings" (record every meeting without sending a link) was **not end-to-end verified on real meetings**, notwithstanding source-level regression tests that passed. Therefore it is **not currently offered as a paid feature**. It is disabled on the running controller via `AUTO_ALL_MEETINGS_ENABLED=false` and defaults to disabled in source.

- Removed the "All Meetings" button from all three localized persistent reply keyboards, bot slash-command lists (FA/EN/DE + admin), paid-feature advertisements, /start onboarding, and English/Persian landing pages.
- Direct legacy `/auto` commands now explicitly tell the user it is temporarily unavailable. `/auto off` still disables previously saved settings.
- Previous enabled auto flags are persisted as `false` during startup. Existing OAuth credentials remain stored and available for normal manual invite/calendar lookup; no tokens are deleted. The feature will require opt-in again if restored.
- Personal auto-calendar scanning and new OAuth auto-enablement are gated by this setting. Sending a single Meet link for a scheduled meeting (with recorder invited to the event) and `/now` for current meetings are unaffected.

## What "2 hours per month" means

Every new one-time plan has **30-day validity from its own period start** (not calendar month, not recurring billing), and a **TOTAL** quota of completed recordings across all meetings:

| Plan | Price in toman | Recordings available per 30-day period |
|---|---:|---:|
| Basic | 298,000 | 2 hours (120 minutes) |
| Pro | 498,000 | 6 hours (360 minutes) |
| Business | 998,000 | 15 hours (900 minutes) |

Examples: A Basic customer can record four different 30-minute meetings, or one 90-minute meeting plus one 30-minute meeting. Completed recording durations reduce the total. A meeting already in progress can finish even if it exceeds the remaining quota; it may push actual used hours above the planned amount.

No automatic charges for overages, no automatic renewal. Unused minutes **expire** at the end of the 30 days. If the customer exhausts all 120 minutes on day 6, they cannot initiate another paid recording under the current Basic period.

**Buying Basic a second time while a paid period is active DOES NOT give 2 extra hours immediately.** It purchases a *new* 30-day period starting after the previously purchased final paid period ends. This also applies to purchasing Pro/Business early. There is currently **no self-service instant top-up product**; for additional immediate credit, the customer is directed to support for manually arranged upgrades.

Subscription `/plans` now displays the active plan, remaining minutes and any pre-purchased upcoming period's plan/start/end. Checkout completion distinguishes:
- New customer/currently inactive: "plan active now" with correct end date and total hours.
- Already active customer: "next period purchased, current balance unchanged" with exact future start and end dates.
- Existing legacy plan: preserved original terms and dedicated legacy receipt message.

No ledger or billing scheme was changed. The existing `activate_subscription` behavior remains future-scheduled for second purchases; regression tests verify no immediate top-up.

## Test and production evidence

- GitHub Actions validation before deployment: [run 44503088675](https://github.com/hsdarestani/beonmeet/actions/runs/44503088675); final branch validation passed before live rollout.
- Read-only source audit: [run 44503644205](https://github.com/hsdarestani/beonmeet/actions/runs/44503644205). Three production Python files were byte-identical to previously reviewed commit `1e6319bd41d848d75c1659074640aa0b02d8f906`, despite being marked modified relative to the much older detached git HEAD.
- Successful guarded live rollout: [run 44503883006](https://github.com/hsdarestani/beonmeet/actions/runs/44503883006). Recording/queue/delivery idle checks, SQLite + state backup, postrestart local and external HTTP health, Persian/English landing copy, five recorder slots, nginx and neighboring CamCam checks passed.
- Telegram `getMyCommands` confirmed hidden `/auto` for FA, EN and DE private-chat scopes.
- Production rollback backup: `/opt/beonmeet/.hide-auto-billing-backup-20261119T101520`.
- Temporary GitHub Actions SSH deployment was removed immediately afterwards.

## Remaining launch limits

This release **does not fix the separate Zibal result 115 ('invalid IP 143.20.60.195')** or prove a real payment transaction. Paid promotion remains blocked until the merchant IP is authorized and the end-to-end payment/activation test succeeds. Synthetic 5-stream tests do not prove five actual Meet rooms either. Do not advertise the disabled All Meetings feature or guarantee five simultaneous Meet recordings without real end-to-end evidence.
