#!/usr/bin/env python3
from pathlib import Path

path = Path("upstream/src/bots/GoogleMeetBot.ts")
source = path.read_text()

old_prejoin = """        this._logger.info('Waiting for the input field to be visible...', {
          joinRequestAttempt,
          maxJoinRequestAttempts
        });
        await retryActionWithWait(
          'Waiting for the input field',
          async () => await this.page.locator(nameInputSelector).first().waitFor({ state: 'visible', timeout: 10000 }),
          this._logger,
          3,
          15000,
          async () => {
            await uploadDebugImage(await this.page.screenshot({ type: 'png', fullPage: true }), 'text-input-field-wait', userId, this._logger, botId);
          }
        );

        this._logger.info('Filling the input field with the name...');
        await this.page.locator(nameInputSelector).first().fill(displayName);
"""

new_prejoin = """        this._logger.info('Waiting for Google Meet pre-join controls...', {
          joinRequestAttempt,
          maxJoinRequestAttempts
        });
        await retryActionWithWait(
          'Waiting for Google Meet pre-join controls',
          async () => {
            const nameVisible = await this.page.locator(nameInputSelector).first().isVisible({ timeout: 1500 }).catch(() => false);
            const joinButtonVisible = await this.page.locator('button').filter({
              hasText: /Ask to join|Join now|Join anyway|Teilnahme erbitten|Jetzt teilnehmen|Trotzdem teilnehmen/i
            }).first().isVisible({ timeout: 1500 }).catch(() => false);
            if (!nameVisible && !joinButtonVisible) {
              throw new Error('Google Meet pre-join controls are not ready yet');
            }
          },
          this._logger,
          4,
          5000,
          async () => {
            await uploadDebugImage(await this.page.screenshot({ type: 'png', fullPage: true }), 'prejoin-controls-wait', userId, this._logger, botId);
          }
        );

        const nameInput = this.page.locator(nameInputSelector).first();
        const hasGuestNameInput = await nameInput.isVisible({ timeout: 1000 }).catch(() => false);
        if (hasGuestNameInput) {
          this._logger.info('Guest pre-join detected, filling display name...');
          await nameInput.fill(displayName);
        } else {
          this._logger.info('Signed-in Google Meet pre-join detected; no guest name field is required.');
        }
"""

if old_prejoin not in source:
    raise SystemExit("PREJOIN_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_prejoin, new_prejoin, 1)

old_bridge = """    await this.page.exposeFunction('screenAppMeetEnd', (slightlySecretId: string, recordedDurationSeconds?: number) => {
      if (slightlySecretId !== this.slightlySecretId) return;
      try {
        if (typeof recordedDurationSeconds === 'number') {
          uploader.setRecordingDuration(recordedDurationSeconds);
        }
        this._logger.info('Attempt to end meeting early...');
        waitingPromise.resolveEarly();
      } catch (error) {
        console.error('Could not process meeting end event', error);
      }
    });

    const { mimeTypes } = getRecordingMimeTypesForExtension(config.uploaderFileExtension);
"""

new_bridge = """    await this.page.exposeFunction('screenAppMeetEnd', (slightlySecretId: string, recordedDurationSeconds?: number) => {
      if (slightlySecretId !== this.slightlySecretId) return;
      try {
        if (typeof recordedDurationSeconds === 'number') {
          uploader.setRecordingDuration(recordedDurationSeconds);
        }
        this._logger.info('Attempt to end meeting early...');
        waitingPromise.resolveEarly();
      } catch (error) {
        console.error('Could not process meeting end event', error);
      }
    });

    await this.page.exposeFunction('beOnMeetRecordingStarted', async (slightlySecretId: string) => {
      if (slightlySecretId !== this.slightlySecretId) return;
      const callbackUrl = process.env.CONTROLLER_RECORDING_STARTED_URL;
      const secret = process.env.INTERNAL_SECRET;
      if (!callbackUrl || !secret) return;
      try {
        const response = await fetch(callbackUrl, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-beonmeet-secret': secret,
          },
          body: JSON.stringify({
            userId,
            eventId: eventId || botId || '',
            botId: botId || eventId || '',
          }),
        });
        if (!response.ok) {
          this._logger.warn('BeOnMeet recording-start callback failed', { status: response.status });
        }
      } catch (error) {
        this._logger.warn('BeOnMeet recording-start callback error', { error });
      }
    });

    const { mimeTypes } = getRecordingMimeTypesForExtension(config.uploaderFileExtension);
"""

if old_bridge not in source:
    raise SystemExit("RECORDING_BRIDGE_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_bridge, new_bridge, 1)

old_start = """          const chunkDuration = 2000;
          mediaRecorder.start(chunkDuration);
          const recordingStartedAt = Date.now();
"""
new_start = """          const chunkDuration = 2000;
          mediaRecorder.start(chunkDuration);
          await (window as any).beOnMeetRecordingStarted(slightlySecretId);
          const recordingStartedAt = Date.now();
"""
if old_start not in source:
    raise SystemExit("RECORDING_START_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_start, new_start, 1)

path.write_text(source)
print("BeOnMeet upstream Google Meet fixes applied")
