#!/usr/bin/env python3
"""Fail-closed overlay for Google Meet trusted admission clicks.

Google Meet can ignore HTMLElement.click(), whose dispatched mouse event has
isTrusted=false, without throwing. The previous recorder erroneously logged
such a click as successful and immediately notified Telegram "ask host Admit",
even if Google never accepted the request. Always use Playwright's browser-
input click and confirm a genuine pending admission UI before telling Telegram.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

SYNTHETIC_CLICK = re.compile(
    r"const clickedByDomText = await this\.page\.evaluate\(\(buttonText\) => \{[\s\S]*?\}, text\);"
)

NOTIFY_BEFORE = """                if (beOnMeetAskedToJoin) {
                    await notifyBeOnMeetWaitingForAdmission();
                }
                let waitTimeout;"""

NOTIFY_AFTER = """                if (beOnMeetAskedToJoin) {
                    // A successful Playwright click is not proof that Google
                    // accepted the knock. Confirm the *pending* lobby state.
                    const knockConfirmed = await this.page.waitForFunction(() => {
                        const body = String(document.body?.innerText || '').toLowerCase();
                        return [
                            'asking to join',
                            'someone in the call should let you in soon',
                            'someone in the meeting should let you in soon',
                            "you'll join the call when someone lets you in",
                            'waiting for someone to let you in',
                            'your request to join is pending',
                            'bitte warten sie, bis sie vom organis',
                            'warten sie, bis sie',
                        ].some(phrase => body.includes(phrase));
                    }, null, { timeout: 5000 }).then(() => true).catch(() => false);
                    if (knockConfirmed) {
                        await notifyBeOnMeetWaitingForAdmission();
                    } else {
                        // If Ask to join is still visible, Google did NOT move
                        // from the prejoin UI. The job must fail/retry rather
                        // than falsely pretending the host was notified.
                        const askStillVisible = await this.page.locator('button')
                            .filter({ hasText: /Ask to join|Teilnahme erbitten/i })
                            .first().isVisible({ timeout: 900 }).catch(() => false);
                        if (askStillVisible) {
                            this._logger.warn('Google Meet did not accept the trusted Ask to join click...');
                            throw new Error('Google Meet guest join request was not accepted');
                        }
                        // No known lobby text, but join button disappeared:
                        // admit might already have happened. Let the existing
                        // participant-verification loop determine the truth.
                        this._logger.info('Meet lobby state unconfirmed after join click; awaiting verification...');
                    }
                }
                let waitTimeout;"""


def patched_source(source: str) -> str:
    if "GOOGLE_MEET_TRUSTED_JOIN_PATCH" in source:
        raise ValueError("Trusted join patch already applied")
    matches = list(SYNTHETIC_CLICK.finditer(source))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one synthetic click branch; found {len(matches)}")
    old = matches[0].group()
    for required in ("button.click()", "document.querySelectorAll('button')", "return true"):
        if required not in old:
            raise ValueError(f"Unexpected synthetic click implementation: {required}")
    if source.count(NOTIFY_BEFORE) != 1:
        raise ValueError("Original premature admission callback block mismatch")
    source = source[:matches[0].start()] + (
        "// GOOGLE_MEET_TRUSTED_JOIN_PATCH: No HTMLElement.click() for admission.\n"
        "                            const clickedByDomText = false;"
    ) + source[matches[0].end():]
    source = source.replace(NOTIFY_BEFORE, NOTIFY_AFTER, 1)
    assert source.count("GOOGLE_MEET_TRUSTED_JOIN_PATCH") == 1
    assert source.count("const knockConfirmed =") == 1
    return source


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path)
    p.add_argument("destination",type=Path)
    args=p.parse_args()
    if args.source.resolve()==args.destination.resolve():
        raise SystemExit("Refusing to alter live code in place")
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")),encoding="utf-8")
    args.destination.chmod(0o644)
    print("TRUSTED_MEET_JOIN_OVERLAY_READY")
