#!/usr/bin/env python3
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

required = [
    '@app.get("/privacy"',
    '@app.get("/privacy-policy"',
    '@app.get("/terms"',
    '@app.get("/terms-of-service"',
    "Google API Services User Data Policy",
    "Limited Use requirements",
    "not sold",
    "not used for advertising or ad targeting",
    "read only",
    "up to 72 hours",
]
for needle in required:
    assert needle in MAIN, f"missing public OAuth verification requirement: {needle}"

print("PUBLIC_OAUTH_PAGES_TEST_PASS")
