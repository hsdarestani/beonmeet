# BeOnMeet Remote Recorder Worker

This stack is an optional horizontal recorder node.

It makes outbound HTTPS requests to the main BeOnMeet controller, so the recorder
server does not need to expose its meeting-bot port to the public internet.

## Required worker.env

```env
CONTROLLER_BASE_URL=https://beonmeet.smarbiz.sbs
INTERNAL_SECRET=<same controller internal secret>
WORKER_ID=worker-eu-01
WORKER_POOL=free
WORKER_SLOTS=4
```

`WORKER_POOL` is either `free` or `premium`.

The agent sends heartbeats, pulls queued jobs, submits them to the local meeting
bot, and requeues a job if local launch fails. Finished recordings stream back to
the controller over HTTPS rather than relying on a shared filesystem.

A signed-in Chrome profile must exist at `chrome-profile/`. Never share that
profile publicly or commit it to Git.
