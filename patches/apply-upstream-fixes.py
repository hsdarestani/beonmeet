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

old_admission_point = """        // Do this to ensure meeting bot has joined the meeting
        const wanderingTime = config.joinWaitTime * 60 * 1000; // Give some time to admit the bot
"""
new_admission_point = """        // Do this to ensure meeting bot has joined the meeting
        const wanderingTime = config.joinWaitTime * 60 * 1000; // Give some time to admit the bot
        let beOnMeetAdmissionNotified = false;
        const notifyBeOnMeetWaitingForAdmission = async () => {
          if (beOnMeetAdmissionNotified) return;
          const callbackUrl = process.env.CONTROLLER_WAITING_FOR_ADMISSION_URL;
          const secret = process.env.INTERNAL_SECRET;
          if (!callbackUrl || !secret) return;
          beOnMeetAdmissionNotified = true;
          try {
            await fetch(callbackUrl, {
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
          } catch (error) {
            this._logger.warn('BeOnMeet admission callback error', { error });
          }
        };
"""
if old_admission_point not in source:
    raise SystemExit("ADMISSION_HELPER_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_admission_point, new_admission_point, 1)

old_lobby_detection = """                const lobbyHostWaitingTexts = [
                  GOOGLE_LOBBY_MODE_HOST_TEXT,
                  'Bitte warten Sie, bis Sie vom Organisator',
                ];
                for (const text of lobbyHostWaitingTexts) {
                  const lobbyModeHostWaitingText = await this.page.getByText(text);
                  if (await lobbyModeHostWaitingText.count() > 0 && await lobbyModeHostWaitingText.first().isVisible()) {
                    return 'WAITING_FOR_HOST_TO_ADMIT_BOT';
                  }
                }
"""
new_lobby_detection = """                const lobbyHostWaitingTexts = [
                  GOOGLE_LOBBY_MODE_HOST_TEXT,
                  'Bitte warten Sie, bis Sie vom Organisator',
                  'Asking to join',
                  'Someone in the call should let you in soon',
                  "You'll join the call when someone lets you in",
                  'Waiting for someone to let you in',
                  'Your request to join is pending',
                ];
                const bodyText = (await this.page.evaluate(() => document.body.innerText).catch(() => '')) || '';
                for (const text of lobbyHostWaitingTexts) {
                  if (bodyText.toLowerCase().includes(text.toLowerCase())) {
                    return 'WAITING_FOR_HOST_TO_ADMIT_BOT';
                  }
                  const lobbyModeHostWaitingText = await this.page.getByText(text, { exact: false }).first();
                  if (await lobbyModeHostWaitingText.count() > 0 && await lobbyModeHostWaitingText.isVisible().catch(() => false)) {
                    return 'WAITING_FOR_HOST_TO_ADMIT_BOT';
                  }
                }
"""
if old_lobby_detection not in source:
    raise SystemExit("LOBBY_TEXT_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_lobby_detection, new_lobby_detection, 1)

old_wait_branch = """              if (lobbyModeHostWaitingText === 'WAITING_FOR_HOST_TO_ADMIT_BOT') {
                this._logger.info('Lobbdy Mode: Google Meet Bot is waiting for the host to admit it...', { userId, teamId });
"""
new_wait_branch = """              if (lobbyModeHostWaitingText === 'WAITING_FOR_HOST_TO_ADMIT_BOT') {
                this._logger.info('Lobby Mode: Google Meet Bot is waiting for the host to admit it...', { userId, teamId });
                await notifyBeOnMeetWaitingForAdmission();
"""
if old_wait_branch not in source:
    raise SystemExit("WAIT_BRANCH_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_wait_branch, new_wait_branch, 1)

old_count = """                        if (match && parseInt(match[1]) >= 1) {
                          return true;
                        }
"""
new_count = """                        if (match && parseInt(match[1]) >= 2) {
                          return true;
                        }
"""
if old_count not in source:
    raise SystemExit("PARTICIPANT_COUNT_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_count, new_count, 1)

old_alt = """                        if (label && /People.*?\d+/.test(label)) {
                          return true;
                        }
"""
new_alt = """                        if (label && /People.*?\d+/.test(label)) {
                          const match = label.match(/People.*?(\d+)/);
                          if (match && parseInt(match[1]) >= 2) {
                            return true;
                          }
                        }
"""
if old_alt not in source:
    raise SystemExit("ALT_PARTICIPANT_COUNT_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_alt, new_alt, 1)

old_fallback = """                      // Fallback: Check for Leave call button which indicates we're in a call
                      const leaveCallButton = document.querySelector('button[aria-label="Leave call"], button[aria-label="Anruf verlassen"]');
                      if (leaveCallButton) {
                        // If we have Leave call button AND no lobby mode text, we're likely in the call
                        const hasLobbyText = bodyText.includes('Asking to join') ||
                                            bodyText.includes('You\'re the only one here') ||
                                            bodyText.includes('Teilnahme erbitten') ||
                                            bodyText.includes('Bitte warten Sie, bis Sie vom Organisator');
                        if (!hasLobbyText) {
                          return true;
                        }
                      }

                      return false;
"""
new_fallback = """                      // Do not treat the Leave button alone as proof of admission.
                      // Google shows call controls while a user is still waiting in the lobby.
                      return false;
"""
if old_fallback not in source:
    raise SystemExit("LEAVE_BUTTON_PATCH_MARKER_NOT_FOUND")
source = source.replace(old_fallback, new_fallback, 1)

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
