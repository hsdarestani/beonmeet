#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = (ROOT / "app" / "admin_panel.py").read_text(encoding="utf-8")

required = [
    "--blue:#4285F4",
    "--red:#EA4335",
    "--yellow:#FBBC05",
    "--green:#34A853",
    "--shadow-card:",
    "--shadow-pressed:",
    "border-radius:32px",
    "active{{transform:scale(.94)",
    "@media(prefers-reduced-motion:reduce)",
    "class=\"clay-ambient\"",
    "class=\"card section google-card\"",
    "class=\"card section subscription-card\"",
    "Google Calendar و همه جلسات",
    "nav-auto",
]
for needle in required:
    assert needle in ADMIN, f"missing Google clay admin invariant: {needle}"

assert "#080a12" not in ADMIN
assert "background:#0b0e17cc" not in ADMIN

print("ADMIN_GOOGLE_CLAY_TEST_PASS")
