#!/usr/bin/env python3
"""Fail-closed compiled worker admission callback overlay regression test."""
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "patches" / "patch_live_admission_notice.py"
spec = importlib.util.spec_from_file_location("admission_patch", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

source = (
    "const notifyBeOnMeetWaitingForAdmission = async () => {\n"
    + module.FLAG_DECLARATION + "\n"
    + module.CLICK + "\n"
    + module.CLICK + "\n"
    + module.CALLBACK_END + "\n"
)
assert chr(10) in module.FLAG_PATCHED, "Compiled JS must contain a real linebreak after the flag declaration"
patched = module.patched_source(source)
assert patched.count("let beOnMeetAskedToJoin = false") == 1
assert patched.count("beOnMeetAskedToJoin = /Ask to join") == 2
assert patched.count("await notifyBeOnMeetWaitingForAdmission();") == 1
assert patched.index("let beOnMeetAskedToJoin = false") < patched.index("beOnMeetAskedToJoin = /Ask to join")
assert patched.index("await notifyBeOnMeetWaitingForAdmission();") > patched.index(
    "const notifyBeOnMeetWaitingForAdmission = async () => {"
)
for invalid in (source.replace(module.CLICK, "", 1), source.replace(module.CALLBACK_END, "")):
    try:
        module.patched_source(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Must reject unexpected compiled worker source")
try:
    module.patched_source(patched)
except ValueError:
    pass
else:
    raise AssertionError("Overlay must reject duplicate application")
print("MEET_ADMISSION_OVERLAY_TEST_PASS")
