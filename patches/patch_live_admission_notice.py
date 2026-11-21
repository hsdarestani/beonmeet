#!/usr/bin/env python3
"""Versioned, fail-closed patch to the existing compiled Meet worker.

Use on a copy of the low-resource overlay only. Never patch live containers in
place while jobs are active. The owning release workflow backs up and validates.
"""
from __future__ import annotations

import argparse
from pathlib import Path

CLICK = '''buttonClicked = true;
                                this._logger.info(`Success clicked using "${text}" action...`, {'''
CLICK_PATCHED = '''buttonClicked = true;
                                // Remember when the host must approve a guest.
                                beOnMeetAskedToJoin = /Ask to join|Teilnahme erbitten/i.test(text);
                                this._logger.info(`Success clicked using "${text}" action...`, {'''

FLAG_DECLARATION = "this._logger.info('Waiting for Google Meet pre-join controls...', {"
FLAG_PATCHED = "let beOnMeetAskedToJoin = false;\n                " + FLAG_DECLARATION

CALLBACK_END = '''                };
                let waitTimeout;'''
CALLBACK_PATCHED = '''                };
                // Google Meet may change its lobby text. Notify immediately
                // after clicking "Ask to join" rather than relying exclusively
                // on brittle DOM text matching in the subsequent wait loop.
                if (beOnMeetAskedToJoin) {
                    await notifyBeOnMeetWaitingForAdmission();
                }
                let waitTimeout;'''


def patched_source(source: str) -> str:
    if "beOnMeetAskedToJoin" in source:
        raise ValueError("Already patched; refuse double application")
    if source.count(FLAG_DECLARATION) != 1:
        raise ValueError("Expected exactly one prejoin logging anchor")
    if source.count(CLICK) != 2:
        raise ValueError(f"Expected two click paths, got {source.count(CLICK)}")
    if source.count(CALLBACK_END) != 1:
        raise ValueError("Expected exactly one admission helper exit anchor")
    if source.count("const notifyBeOnMeetWaitingForAdmission = async () => {") != 1:
        raise ValueError("Missing original secured admission callback")
    output = source.replace(FLAG_DECLARATION, FLAG_PATCHED, 1)
    output = output.replace(CLICK, CLICK_PATCHED)
    output = output.replace(CALLBACK_END, CALLBACK_PATCHED, 1)
    assert output.count("beOnMeetAskedToJoin") == 4
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise SystemExit("Refuse in-place patch without guarded rollout")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(patched_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    args.destination.chmod(0o644)
    print("MEET_ADMISSION_NOTICE_OVERLAY_PATCHED")
