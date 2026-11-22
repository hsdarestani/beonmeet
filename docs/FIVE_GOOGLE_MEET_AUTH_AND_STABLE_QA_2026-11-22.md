# BeOnMeet — Google Account vs Meet admission: corrected live findings (2026-11-22)

## What was actually verified

The owner showed a screenshot of an authenticated Google Account page in the original BeOnMeet Chrome. The earlier conclusion that the browser account had signed out **was not proved and must not be repeated**. A redirect from the bare `meet.google.com/` homepage to the Google Workspace marketing site, by itself, is **not** a valid authentication gate.

Direct Chrome probes in the same production browser and every isolated browser demonstrated that the existing private test meeting URLs still load real Google Meet prejoin pages, HTTP 200, with `Ask to join` controls. The test UI also displayed a `Sign in` button, so the probes do not prove that Google Meet itself recognizes the session as authenticated; neither should they be described as a total sign-out. An explicit, hosted room is needed to establish admission and recording.

- [Original Chrome, account and direct meeting URL comparison](https://github.com/hsdarestani/beonmeet/actions/runs/45011465274)
- [Five independent Chrome prejoin pages (all five 200; Ask to join)](https://github.com/hsdarestani/beonmeet/actions/runs/45011580972)
- [Five actual room admission test failed, only one recording-started](https://github.com/hsdarestani/beonmeet/actions/runs/45006471901)
- [Five synthetic 720p/15fps video+audio files passed](https://github.com/hsdarestani/beonmeet/actions/runs/45005936763)

## Confirmed repair of the original Chrome and four cloned Google sessions

The original Chrome DevTools HTTP and raw WebSocket both worked but Playwright CDP attachment timed out while one `accounts.google.com` login-flow tab remained stuck. With all production workers idle, an automated guarded action created a replacement `about:blank` page and closed **only** that blocked tab. It did **not** restart the Chrome container, delete the account profile, or touch CamCam; Playwright immediately reconnected. [Surgical CDP recovery evidence](https://github.com/hsdarestani/beonmeet/actions/runs/45012754247).

The direct-room check then showed that the original authenticated Chrome had **Join now** without Sign in, while cloned browsers 2–5 had **Ask to join** plus Sign in. That discrepancy explains why copying Chrome profile folders had not actually replicated a usable Meet sign-in. [Five-lane before synchronization evidence](https://github.com/hsdarestani/beonmeet/actions/runs/45012847410).

A guarded, **on-host-only** session synchronization then copied the BeOnMeet recorder's existing eligible Google session cookies from the original signed-in Chrome to its four private QA browser profiles through local CDP; no cookie or password values were logged, stored in Git or transmitted off host. All four clones independently verified a signed-in **Join now** Meet state after the transfer, and the original remained signed in. [Five-lane sign-in repair passed](https://github.com/hsdarestani/beonmeet/actions/runs/45013023805).

This verifies the **five browser authentication states**, not concurrent actual media capture or successful deliveries. A separate five-real-room test is still required with host-admitted/controlled sessions and media-file verification.

## Five genuine concurrent Google Meet recording-start events now proved

After the repaired source Chrome's signed-in session was synchronized locally to the four isolated browsers, the existing five-room QA was rerun with five independently bound, one-job recorder workers plus one temporary fifth QA profile. Five distinct private Meet rooms accepted jobs, **all five issued actual `recording-started` callbacks**, and all five reported running jobs for **at least 60 consecutive seconds**. No customer billing/Telegram callbacks were invoked and the main BeOnMeet/CamCam services stayed healthy. [Successful five-real-room test](https://github.com/hsdarestani/beonmeet/actions/runs/45006471901).

A separate, more stringent after-test preflight verified all five permanent Chrome lanes showed **Join now** with **no** Sign in prompt. [Five authenticated Chrome recheck](https://github.com/hsdarestani/beonmeet/actions/runs/45013282807).

This is a meaningful real-room admission and simultaneous start test, but **does not validate five 60-minute capture files or delivery**, because the QA worker processes were stopped once the one-minute overlap condition was satisfied. Continue to gate production five-lane cutover on sustained real media/audio, complete file verification and duration.

## Corrected automated test behavior

`qa-restore-five-google-sessions.yml` has been changed into an **idle-only, credential-neutral direct-room preflight**. It reads five private existing test links from `/opt/beonmeet/.five-isolated-runtime/qa_meet_links.json`, opens each in its isolated Chrome, and requires HTTP 200 with a real Meet room URL, a signed-in **Join now** UI and **no** Sign in prompt, never a marketing redirect, invalid room or other page.

This is **actual signed-in Meet prejoin verification in bot-owned private QA rooms**, not evidence of five simultaneous admissions or recordings. The workflow no longer copies Google cookies across profiles, alters the owner's login, creates meetings or sends invites. The legacy `meet.google.com/` landing-page auth gate was wrong for this environment.

## Why five real sessions failed despite five 720p synthetic successes

Five Worker processes and five CDPs ran simultaneously, with plenty of RAM; however, only one of five real Meet tests emitted a `recording-started` callback. Several other rooms remained at the `Ask to join` / prejoin stage, and the original QA fixture created temporary `meet.new` rooms then closed the page that created them. There were **no five consenting live hosts present to admit the recorders**, so it is not a valid five-room acceptance test. The precise cause of each Google redirect/timeout remains unproven.

One earlier real-room canary delivered a tiny 159,488-byte file after around four minutes; its audio/video validity is **still unverified**. Never interpret upload success as a valid recording.

## Remaining acceptance gate

Create five independent meetings with organizers actually present and able to admit the recorder, preferably using non-ephemeral invitations. Then:
1. Verify each Worker can join the room and obtain genuine in-call controls.
2. Confirm five distinct `recording-started` callbacks and five simultaneous real media sessions.
3. Run five separate, consented 60-minute sessions with audio/video from other participants and confirm five fully playable, correctly isolated recordings, five deliveries and correct billing.
4. Observe Chrome CPU, memory, WebRTC, CamCam, recording temp disk and recovery throughout.

Until then, keep live BeOnMeet production routing on the original serialized one-room path. Five standby Chrome/Worker pairs remain staged; no promise of five simultaneous real recordings is justified yet.

No Google password or tokens should be entered into GitHub Actions, scripts or chat. The owner does **not** need to reauthenticate solely because of the Google Workspace landing-page redirect.
