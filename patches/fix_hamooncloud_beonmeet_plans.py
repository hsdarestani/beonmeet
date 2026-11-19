#!/usr/bin/env python3
"""Minimal idempotent patch for HamoonCloud's BeOnMeet plan allowlist.

A separate on-host HamoonCloud source tree serves pay.hamooncloud.ir. This
patch must ONLY change its BeOnMeet route's plan check; other services and
CamCam payment logic must be untouched.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = "!['monthly','quarterly','halfyear'].includes(plan)"
NEW = "!['monthly','quarterly','halfyear','basic','pro','business'].includes(plan)"
START = "app.get('/payments/beonmeet/start'"
END = "app.get('/payments/beonmeet/verify'"


def patch(source: str) -> str:
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError("Unknown gateway route layout")
    head, beonmeet_tail = source.split(START, 1)
    body, tail = beonmeet_tail.split(END, 1)
    if body.count(NEW) == 1 and OLD not in body:
        return source
    if body.count(OLD) != 1 or NEW in body:
        raise ValueError("Unknown or ambiguous existing BeOnMeet allowlist")
    assert OLD not in head and OLD not in tail, "Only BeOnMeet should use this exact check"
    return head + START + body.replace(OLD, NEW) + END + tail


def main() -> None:
    a=argparse.ArgumentParser()
    a.add_argument("original",type=Path)
    a.add_argument("patched",type=Path)
    opts=a.parse_args()
    if opts.original.resolve()==opts.patched.resolve():
        raise SystemExit("Refusing in-place edit")
    source=opts.original.read_text(encoding="utf-8")
    out=patch(source)
    opts.patched.write_text(out,encoding="utf-8")
    print("HAMOONCLOUD_BEONMEET_PLAN_ALLOWLIST_PATCH_OK")


if __name__=="__main__":
    main()
