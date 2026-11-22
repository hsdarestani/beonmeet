# Google Meet authentication and five-real-room QA (2026-11-22)

## Root cause (verified live)
The Google recorder profile is **not currently signed in to Meet**, despite having Google auth-shaped cookies. A browser navigation to `https://meet.google.com/` redirected **both the original production Chrome and each of four isolated Chrome containers** to `workspace.google.com`. A navigation to `https://meet.new/` sent an isolated Chrome to `accounts.google.com` sign-in. The previous cookie-marker health check was a false positive.

Evidence:
- [Original and four-clone redirect comparison](https://github.com/hsdarestani/beonmeet/actions/runs/45009928100)
- [Meet landing and instant link diagnosis](https://github.com/hsdarestani/beonmeet/actions/runs/45009805796)
- [Five-way actual Meet test: only one recording-started](https://github.com/hsdarestani/beonmeet/actions/runs/45006471901)
- [Safe auth restore readiness test: fails closed with SOURCE_GOOGLE_LOGIN_EXPIRED](https://github.com/hsdarestani/beonmeet/actions/runs/45010394833)

`meet.new` creates instant meeting rooms and may be invalid if nobody remains; it is **not** an appropriate five-room acceptance fixture. Use the authenticated Meet UI `New meeting > Create a meeting for later` and ensure participants/hosts can join those rooms legitimately. These are not a substitute for a consented, hosted 60-minute endurance test.

## Single owner-controlled action to restore Google auth

The VPS has a noVNC browser UI bound to **localhost only** on TCP 6081. It was verified as available with HTTP 200, and it should never be opened publicly without a secure gateway.

On the owner's Windows terminal:

```powershell
ssh -p 9011 -L 6081:127.0.0.1:6081 root@143.20.60.195
```

Leave that SSH tunnel running. On the **owner's computer only** open:

`http://localhost:6081/vnc.html?autoconnect=true`

In the visible original recorder Chrome, sign in to the authorized BeOnMeet Google account. Complete any verification/challenge; never disclose the Google password, recovery codes, or 2FA tokens in ChatGPT, GitHub Actions, Telegram or logs.

After confirming `meet.google.com` opens rather than redirecting to Google Workspace, rerun the **failed** GitHub job for workflow `qa-restore-five-google-sessions.yml` (or start a new deployment job on the approved branch if needed). It will:
1. Refuse unless BeOnMeet and CamCam are healthy and no live jobs/queues/deliveries exist.
2. Confirm original Chrome actually reaches authenticated Meet, and propagate valid Google cookies **inside this VPS only**, without logging credential values, to the four protected Chrome profiles.
3. Confirm each isolated Chrome can navigate to authenticated Meet. Fail closed otherwise.
4. Create five unique, private "Create for later" meeting links, never send invitations, and store them only as mode-0600 `/opt/beonmeet/.five-isolated-runtime/qa_meet_links.json`.
5. Do NOT alter controller routing, subscription credits, Telegram messages or customer files.

Then rerun five-room real Meet join acceptance with qualified/consenting hosts and evaluate AV files. Only cut over `FREE_WORKER_URLS` and `PREMIUM_WORKER_URLS` after five real independent 60-minute recording **and** delivery validations pass.

## Guardrails

- Original controller retains one real Meet session at a time until real acceptance. The five independent Chrome+worker lanes stay staged, and CamCam is untouched.
- The previous test's five successful synthetic 720p AV files do not prove Meet admission or robust recording of actual people.
- The previous real-room test emitted a 159,488-byte file for about four minutes; actual stream content and durations remained unverified. An empty/closed host room may yield static/near-empty media. Do not sell five guaranteed sessions based on upload callbacks alone.
- No Google credentials are stored in code, CI logs, documents or chat. The temporary SSH tunnel does not expose the browser VNC port on the internet.
