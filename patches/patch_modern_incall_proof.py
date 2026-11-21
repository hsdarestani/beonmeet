#!/usr/bin/env python3
"""Small, fail-closed patch for current compiled Meet recorder.

The current Meet UI can show a joined bot with a top-right
[data-avatar-count="1"], "Leave call", "Raise hand", chat and microphone
controls, but NO button whose aria-label starts with "People".
The previous join-wait loop required an English People count of at least
2, so it never acknowledged a real Open admission and never started capture.

This patch does not interpret "Leave call" alone as admission. Require
several independent in-call controls, the avatar badge, correct Meet origin,
and the *absence* of join and lobby controls.
"""
from __future__ import annotations
import argparse
from pathlib import Path

LEAVE_OLD = """await this.page.locator('button[aria-label="Leave call"], button[aria-label="Anruf verlassen"]').first().isVisible({ timeout: 500 }).catch(() => false);"""
LEAVE_NEW = """await this.page.locator('button[aria-label*="Leave call"], button[aria-label*="Anruf verlassen"]').first().isVisible({ timeout: 500 }).catch(() => false);"""

FALLBACK_OLD = """                                                // Do not treat the Leave button alone as proof of admission.
                                                // Google shows call controls while a user is still waiting in the lobby.
                                                return false;"""

FALLBACK_NEW = """                                                // BEONMEET_MODERN_IN_CALL_PROOF_V1
                                                // A real Open meeting was observed with no "People" button,
                                                // a global [data-avatar-count="1"], plus in-call controls.
                                                // NEVER accept Leave-call by itself (can exist in lobby).
                                                const labels = Array.from(document.querySelectorAll('button'))
                                                    .map(button => String(button.getAttribute('aria-label') || button.innerText || '').toLowerCase());
                                                const includes = (...pieces) => labels.some(label => pieces.some(piece => label.includes(piece)));
                                                const badge = document.querySelector('[data-avatar-count]');
                                                const badgeCount = Number(badge?.getAttribute('data-avatar-count') || 0);
                                                const hasLeave = includes('leave call', 'anruf verlassen');
                                                const hasHand = includes('raise hand', 'hand heben');
                                                const hasChat = includes('chat', 'nachrichten');
                                                const hasMedia = includes('microphone', 'mikrofon', 'microfon', 'camera', 'kamera');
                                                const hasPrejoinButton = includes('ask to join', 'teilnahme erbitten', 'join now', 'jetzt teilnehmen');
                                                const lowerBody = String(document.body?.innerText || '').toLowerCase();
                                                const pendingAdmission = [
                                                    'asking to join', 'someone in the call should let you in',
                                                    'waiting for someone to let you in', "you'll join the call when",
                                                    'bitte warten sie', 'request to join is pending'
                                                ].some(needle => lowerBody.includes(needle));
                                                if (location.hostname === 'meet.google.com' &&
                                                    Number.isFinite(badgeCount) && badgeCount >= 1 &&
                                                    hasLeave && hasHand && hasChat && hasMedia &&
                                                    !hasPrejoinButton && !pendingAdmission) {
                                                    return true;
                                                }
                                                return false;"""

PREJOIN_SCREENSHOT_OLD = """                }, this._logger, 4, 5000, async () => {
                    await (0, bugService_1.uploadDebugImage)(await this.page.screenshot({ type: 'png', fullPage: true }), 'prejoin-controls-wait', userId, this._logger, botId);
                });"""

PREJOIN_SCREENSHOT_NEW = """                }, this._logger, 4, 5000, async () => {
                    // If a shared Chrome target crashed, a debug screenshot
                    // must not replace the original prejoin failure with a
                    // second unhandled "Target crashed" exception.
                    try {
                        if (!this.page.isClosed()) {
                            await (0, bugService_1.uploadDebugImage)(await this.page.screenshot({ type: 'png', fullPage: true, timeout: 1200 }), 'prejoin-controls-wait', userId, this._logger, botId);
                        }
                    }
                    catch (debugFailure) {
                        this._logger.warn('Meet prejoin debug screenshot skipped after page error', { errorName: debugFailure?.name });
                    }
                });"""


def patched_source(source: str) -> str:
    if "BEONMEET_MODERN_IN_CALL_PROOF_V1" in source:
        raise ValueError("Patch already present")
    anchors = (
        (LEAVE_OLD, LEAVE_NEW),
        (FALLBACK_OLD, FALLBACK_NEW),
        (PREJOIN_SCREENSHOT_OLD, PREJOIN_SCREENSHOT_NEW),
    )
    for old, _ in anchors:
        if source.count(old) != 1:
            raise ValueError(f"Expected one matching compiled source fragment; found {source.count(old)}")
    for old, new in anchors:
        source = source.replace(old, new, 1)
    assert source.count("BEONMEET_MODERN_IN_CALL_PROOF_V1") == 1
    assert source.count("Target crashed") >= 1 or "debug screenshot skipped after page error" in source
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refusing to patch live code in place")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("MEET_STRICT_MODERN_INCALL_PROOF_STAGED")
