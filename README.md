# BeOnMeet

Self hosted Google Meet recorder that watches a dedicated Google Calendar and delivers recordings to the Telegram user who requested them.

## User flow

1. Open the Telegram bot and send the Google Meet URL.
2. Invite `meetrecorderbot@gmail.com` to the Google Calendar event.
3. BeOnMeet detects the matching Calendar event and joins at its start time.
4. The recording is kept only in RAM under `/dev/shm/beonmeet`.
5. When the meeting ends, the recording is sent to the requesting Telegram chat and removed from RAM.

## Initial setup

After deployment, open:

`https://beonmeet.smarbiz.sbs/auth/google`

Sign in as `meetrecorderbot@gmail.com` and allow read-only Calendar access.

The current deployment uses the Telegram cloud Bot API. Files larger than its direct upload limit are converted into playable parts before delivery. A local Telegram Bot API endpoint can be added later for large single-file uploads.

## Recording engine

The deployment pins `screenappai/meeting-bot` at a known commit and replaces only its uploader. Google Meet capture stays upstream while BeOnMeet handles Calendar scheduling and Telegram delivery.
