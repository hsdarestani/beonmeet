# BeOnMeet — 5-stream sustained stress QA — 19 November 2026

## Scope / headline

Existing VPS: **3 vCPU, 5.8 GiB RAM, 30 GB root disk**, shared with CamCam. Production controller advertised 5 slots before, throughout, and after this load test. **No new VPS, no extra recurring hosting charge, no actual Google Meet meetings scheduled or joined.**

- **First 4-minute synthetic run failed**: 4 of 5 MediaRecorder streams wrote bytes, fifth did not despite page/frame loop running. See [run #44491835461](https://github.com/hsdarestani/beonmeet/actions/runs/44491835461). This intermittent issue means five-real-meeting reliability is **not established**.
- **Second 4-minute synthetic run passed fully**: 5 independent 640×360, 8 fps VP8+Opus MediaRecorder audio/video streams ran concurrently, all five streams delivered WebM byte chunks with **zero reported recording errors**. See [run #44492683469](https://github.com/hsdarestani/beonmeet/actions/runs/44492683469).

## Second-run per-stream measurements

| Stream | Expected / detected synthetic audio | Video frame counter | Total encoded bytes | Recorder errors | Capture wall time |
|---|---|---:|---:|---:|---:|
| 1 | 220 Hz / 220 Hz | 1934 | 4,664,729 | 0 | 242 s |
| 2 | 330 Hz / 330 Hz | 1929 | 4,886,815 | 0 | 241 s |
| 3 | 440 Hz / 440 Hz | 1926 | 4,712,785 | 0 | 241 s |
| 4 | 550 Hz / 550 Hz | 1923 | 4,829,994 | 0 | 240 s |
| 5 | 660 Hz / 660 Hz | 1921 | 4,632,547 | 0 | 240 s |

Every file was confirmed by `ffprobe` to contain **both audio and video streams**; decoded audio frequency was verified with a Goertzel detector and matched the correct stream, with no detectable cross-stream confusion in these controlled tones. `ffprobe` did not report a container-level duration, so duration values above are recorder wall-time/counters, not validated WebM duration metadata. Video frame count is based on the browser's source canvas drawing loop; it is not a per-file decoded packet count.

## Host and neighboring service monitoring during the passing run

- Host started with ~3,997 MB available RAM and ~10.09 GB free root disk.
- Lowest sampled available RAM ~**3,183 MB**; no memory-safety abort, no disk-safety abort.
- Sampled 1-minute host load varied up to ~**2.08** on 3 logical vCPUs.
- Synthetic Chrome tested in an **isolated temporary container** (`--cpus=1.3`, `--memory=1800m`) and showed ~49–59% of one CPU and ~590–752 MiB RAM at sampled moments.
- The original production five-slot worker, its Chrome profile and live user meetings were not modified or invoked by the synthetic load generator.
- Four checked CamCam containers (`api`, `pet`, `archive`, `petarchive`) stayed healthy throughout and after the test.
- After the passing run, local BeOnMeet `/health` and worker `/capacity` continued to report five slots, autoscaling remained off, and delivery queues were empty.

## Interpretation

**Passed:** five parallel AV encoders on the shared host with synthetic moving video and distinct generated audio for 4 minutes; no observed CamCam disruption in the sampled checks; all 5 files produced decodable AV streams.

**Not passed/not attempted:** five actual Google Meet logins/joins, permission/admission, incoming WebRTC decoding, `getDisplayMedia` tab capture, distinct meeting recordings and audio capture, long meetings, Telegram media deliveries, transcription and quota decrements. These can be materially more resource-intensive than synthetic canvas encoding. The earlier fifth-stream miss also remains a reliability warning; a single successful run is not a production SLA.

**Go/no-go:** keep the current 5-slot *pilot* configuration for controlled QA only. Before paid advertising claims of guaranteed five simultaneous Google Meet recordings, test five separately hosted, consented Meet rooms concurrently and validate final delivered files and CamCam health. Do not silently claim this test proves actual five-meeting end-to-end operation.

## Cleanup and reproduction

- Test source: `tests/five_sustained_av_smoke.js`; uses Playwright already installed in the BeOnMeet worker container and a short-lived separate Chrome container. Does not use production customer data.
- Passing workflow: `44492683469`. An overlapping CI run failed after 30s waiting on the shared deploy lock; it was not a second host/recording failure.
- Remove temporary remote SSH CI jobs after saving evidence; do not leave recurring load tests tied to pull request edits.
