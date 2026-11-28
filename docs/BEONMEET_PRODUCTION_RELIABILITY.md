# BeOnMeet production reliability

## November 28, 2026 incident

[Latest direct-room preflight](https://github.com/hsdarestani/beonmeet/actions/runs/45013282807) showed a signed-in Meet pre-join screen on all five browsers. It did not join or capture media. A later snapshot showed five healthy transports and only one auth readiness entry. The initial production monitor collapsed missing UI, cookie/session state, expired fixtures, timeouts and transport failures into the same boolean. Two busy workers also had expired proof while still running jobs in the [watchdog rollout evidence](https://github.com/hsdarestani/beonmeet/actions/runs/46141731365). No run demonstrated revocation of all affected Google sessions or a Google same-account concurrency cap.

The controller returned 16 HTTP 500 responses to four workers' recording-ready callbacks. A `PermissionError(13)` arose when checking the exact source file. The controller UID 999 uses group 987. A legacy user directory had lost setgid. Its new job directories inherited group 1001 and mode 2770, so the controller could not traverse them. The recovery loop encountered the same exception and stopped scanning on that pass. No recording reached Telegram processing until directory access was repaired. The earlier worker's pre-join error occurred separately and produced no capture. The sampled containers had zero OOM kills and adequate available memory and disk.

- [Callback and file trace](https://github.com/hsdarestani/beonmeet/actions/runs/46149900808)
- [Group ownership and A/V evidence](https://github.com/hsdarestani/beonmeet/actions/runs/46150095178)
- [Live permission repair](https://github.com/hsdarestani/beonmeet/actions/runs/46150241200) restored the shared group on seven event-mapped directories and restored setgid on their existing user directory. The operation backed up state and original metadata. No service was restarted.
- [Telegram and billing verification](https://github.com/hsdarestani/beonmeet/actions/runs/46150459209) joined controller state and SQLite receipts by original job, owner, and filename. The report withholds private meeting identifiers.

| Worker | Incident result | Verified media duration | Wallet debits |
| --- | --- | ---: | ---: |
| 1 | Pre-join failure, failure notice sent | 0 s | 0 |
| 2 | Video and audio delivered, pipeline complete | 451 s | 1 × 451 s |
| 3 | Video and audio delivered, pipeline complete | 439 s | 1 × 439 s |
| 4 | Video and audio delivered, transcript pending at this snapshot | 385 s | 1 × 385 s |
| 5 | Video and audio delivered, transcript pending at this snapshot | 229 s | 1 × 229 s |

The exact recovery records are in the protected production state and the metadata backup. Recovery used each original owner and event path. Files without an exact ownership record remain untouched.

## Changes under this branch

- Reconcile the tested production release `e6d4089` with `main`. Reuse its persistent media handoff, independently scheduled transcripts, identity-based recovery, and atomic credit reservation. Subsequent live application changes are preserved by a three-way merge at deployment.
- Add lane leases shared by the monitor and controller. A watchdog tab and a new recording cannot share the same lane concurrently. Idle probes distinguish a confirmed Google login challenge from ambiguous UI, transport failures, and busy workers. Keep the original verification timestamp through inconclusive checks and never reissue proof based on a cache.
- Return a retryable response when access or persistence temporarily fails. An inaccessible job remains eligible for recovery and cannot stop checks of other jobs. Connect failures before socket establishment can safely try another lane. Ambiguous HTTP outcomes retain a single assignment.
- Protect recorder monitoring behind the existing administrator login. Report transport, Google readiness, capture, delivery, and resources separately. Repeated explicit Google challenges can notify the configured owner.
- Check inherited shared group when building the recorder uploader. Apply the host metadata repair to existing legacy parents before restarting or changing recorder containers.

## Production acceptance

The incident recovery is separate from release acceptance. Fresh owner-authorized rooms with consenting participants are needed for five simultaneous real recordings for at least 60 minutes. Confirm real admissions and audio/video capture, queue a sixth request, then release a lane and confirm automatic dispatch. Inspect five event-linked delivery receipts, playback, transcription and ledger transactions. Exercise browser and delivery interruption on test jobs only. Repeat the cycle and confirm idle auth stability. Advertising remains gated on these checks.

Automatic reassignment after an ambiguous post, reliable terminal admission-denial signaling, and raw recording durability across a host reboot still need separate verification. Raw worker files currently use the existing host tmpfs mount until the controller persists them to the disk spool.
