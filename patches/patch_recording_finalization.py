#!/usr/bin/env python3
"""Bound the exact production compiled recorder's capture/finalization waits.

The current deployed bot permanently disables participant monitoring after ten
failed badge reads, and waits for a browser callback even after the page closes.
Patch a staged copy only; unexpected upstream layout fails closed.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "BEONMEET_BOUNDED_FINALIZATION_V1"
BRIDGE = "        await this.page.exposeFunction('screenAppSendData', async (slightlySecretId, data) => {"
BRIDGE_NEW = f"""        // {MARKER}: establish the per-page end signal before any browser callback.
        const recordingPage = this.page;
        const processingTime = 60 * 1000;
        const waitingPromise = (0, promise_1.getWaitingPromise)(processingTime + duration);
        const pageTerminated = () => {{
            this._logger.warn('Recording page terminated; finalizing available capture', {{ eventId, botId }});
            waitingPromise.resolveEarly();
        }};
        recordingPage.once('close', pageTerminated);
        recordingPage.once('crash', pageTerminated);
        if (recordingPage.isClosed()) pageTerminated();
{BRIDGE}"""
DATA = "            await uploader.saveDataToTempFile(buffer);"
DATA_NEW = "            if (!(await uploader.saveDataToTempFile(buffer))) throw new Error('Recording chunk persistence failed');"
START = "                await window.beOnMeetRecordingStarted(slightlySecretId);"
START_NEW = "                void window.beOnMeetRecordingStarted(slightlySecretId).catch(() => undefined);"
CHAIN = "                let chunkUploadChain = Promise.resolve();"
CHAIN_NEW = """                const withCaptureDeadline = (work, milliseconds, label) => {
                    let timer;
                    return Promise.race([work, new Promise((_, reject) => {
                        timer = setTimeout(() => reject(new Error(label)), milliseconds);
                    })]).finally(() => clearTimeout(timer));
                };
                let consecutiveChunkFailures = 0;
                let chunkUploadChain = Promise.resolve();"""
WRITE = "                            await sendChunkToServer(arrayBuffer);"
WRITE_NEW = """                            await withCaptureDeadline(sendChunkToServer(arrayBuffer), 15000, 'Recording chunk deadline exceeded');
                            consecutiveChunkFailures = 0;"""
CHUNK_ERROR = "                            console.error('Error uploading chunk:', error);"
CHUNK_ERROR_NEW = """                            console.error('Error uploading chunk:', error);
                            if (++consecutiveChunkFailures >= 3 && !isStoppingRecording) {
                                setTimeout(() => { void stopTheRecording(); }, 0);
                            }"""
STOP_OPEN = "                        await new Promise((resolve) => {\n                            if (mediaRecorder.state === 'inactive') {"
STOP_OPEN_NEW = "                        await withCaptureDeadline(new Promise((resolve) => {\n                            if (mediaRecorder.state === 'inactive') {"
STOP_CLOSE = "                            mediaRecorder.stop();\n                        });\n                        await chunkUploadChain;"
STOP_CLOSE_NEW = """                            mediaRecorder.stop();
                        }), 10000, 'MediaRecorder stop deadline exceeded');
                        await withCaptureDeadline(chunkUploadChain, 25000, 'Recording flush deadline exceeded');"""
END = "                        window.screenAppMeetEnd(slightlySecretId, recordedDurationSeconds);"
END_NEW = "                        await withCaptureDeadline(window.screenAppMeetEnd(slightlySecretId, recordedDurationSeconds), 10000, 'End callback deadline exceeded').catch(() => undefined);"
COUNT_FAILURE = """                                    if (detectionFailures >= maxDetectionFailures) {
                                        console.log('Persistent detection failures:', { bodyText: `${document.body.innerText?.toString()}` });
                                        loneTestDetectionActive = false;
                                    }"""
COUNT_FAILURE_NEW = """                                    // Never turn off participant monitoring because Meet temporarily
                                    // hides its count badge. Unknown count is not proof of departure.
                                    aloneSince = null;
                                    if (detectionFailures % maxDetectionFailures === 0) {
                                        console.warn('Participant count temporarily unavailable; continuing checks');
                                    }"""
COUNT_READ = "                                contributors = getContributorsCount();"
COUNT_READ_NEW = """                                contributors = getContributorsCount();
                                if (typeof contributors === 'undefined' && isOnValidGoogleMeetPage()) {
                                    const text = String(document.body?.innerText || '').toLowerCase();
                                    if (/you(?:'|’)?re the only one here|you are the only one here|you are the only participant|sie sind der einzige teilnehmer/i.test(text)) {
                                        contributors = 1;
                                    }
                                }"""
ALONE = """                    if (hasSeenOtherParticipant) {
                        if (aloneSince === null) {"""
ALONE_NEW = """                    // Positive, sustained count=1 after admission can also end a
                    // room whose earlier participant count was unavailable.
                    if (contributors === 1 && (hasSeenOtherParticipant || now - recordingStartedAt >= 120000)) {
                        if (aloneSince === null) {"""
EVALUATE = "        await this.page.evaluate(async ({ teamId, duration, inactivityLimit, loneParticipantExitDelayMs, userId, slightlySecretId, activateInactivityDetectionAfter, activateInactivityDetectionAfterMinutes, mimeTypes, captureQuality }) => {"
EVALUATE_NEW = "        let evaluateTimer;\n        try {\n        const evaluateCapture = recordingPage.evaluate(async ({ teamId, duration, inactivityLimit, loneParticipantExitDelayMs, userId, slightlySecretId, activateInactivityDetectionAfter, activateInactivityDetectionAfterMinutes, mimeTypes, captureQuality }) => {"
TAIL = """        this._logger.info('Waiting for recording duration', config_1.default.maxRecordingDuration, 'minutes...');
        const processingTime = 0.2 * 60 * 1000;
        const waitingPromise = (0, promise_1.getWaitingPromise)(processingTime + duration);
        waitingPromise.promise.then(async () => {
            const context = this.page.context();
            // For an external CDP browser (the chrome-cdp sidecar), browser.close() only
            // disconnects Playwright — it leaves the Meet tab open, so the bot stays in
            // the call. Close the page (tab) instead, which leaves the meeting and keeps
            // the shared sidecar Chrome alive for the next job.
            if ((0, chromium_1.isExternalBrowserContext)(context)) {
                this._logger.info('Closing the page (external CDP browser stays up)...');
                await this.page.close();
            }
            else {
                this._logger.info('Closing the browser...');
                await context.browser()?.close();
            }
            this._logger.info('Recording stopped and meeting left; finalizing upload next...', { eventId, botId, userId, teamId });
        });
        await waitingPromise.promise;"""
TAIL_NEW = """        await Promise.race([evaluateCapture, new Promise((_, reject) => {
            evaluateTimer = setTimeout(() => reject(new Error('Capture initialization deadline exceeded')), 90000);
        })]);
        } catch (error) {
            this._logger.warn('Recording page evaluation ended; finalizing available capture', { eventId, botId });
            waitingPromise.resolveEarly();
        } finally { clearTimeout(evaluateTimer); }
        this._logger.info('Waiting for recording duration', config_1.default.maxRecordingDuration, 'minutes...');
        await waitingPromise.promise;
        recordingPage.off('close', pageTerminated);
        recordingPage.off('crash', pageTerminated);
        // Close ONLY this recording's owned page. Await cleanup before upload.
        if (!recordingPage.isClosed()) {
            let closeTimer;
            try {
                await Promise.race([recordingPage.close(), new Promise(resolve => { closeTimer = setTimeout(resolve, 10000); })]);
            } catch (error) {
                this._logger.warn('Recording page cleanup failed', { eventId, botId });
            } finally { clearTimeout(closeTimer); }
        }
        this._logger.info('Recording stopped and meeting left; finalizing upload next...', { eventId, botId, userId, teamId });"""


def patched_source(source: str) -> str:
    if MARKER in source:
        raise ValueError("Already patched")
    pairs = [(BRIDGE, BRIDGE_NEW), (DATA, DATA_NEW), (START, START_NEW), (CHAIN, CHAIN_NEW),
             (WRITE, WRITE_NEW), (CHUNK_ERROR, CHUNK_ERROR_NEW), (STOP_OPEN, STOP_OPEN_NEW),
             (STOP_CLOSE, STOP_CLOSE_NEW), (END, END_NEW), (COUNT_FAILURE, COUNT_FAILURE_NEW),
             (COUNT_READ, COUNT_READ_NEW), (ALONE, ALONE_NEW), (EVALUATE, EVALUATE_NEW), (TAIL, TAIL_NEW)]
    for old, new in pairs:
        if source.count(old) != 1:
            raise ValueError("Unexpected compiled source anchor: " + old.splitlines()[0])
        source = source.replace(old, new, 1)
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refusing in-place modification")
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    print("RECORDING_FINALIZATION_OVERLAY_STAGED")
