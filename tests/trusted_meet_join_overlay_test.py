#!/usr/bin/env python3
"""Regression for trusted click and verified Google Meet host-admission notice."""
from pathlib import Path
import importlib.util

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("trusted",root/"patches/patch_trusted_meet_join.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
dom="""const clickedByDomText = await this.page.evaluate((buttonText) => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const button = buttons.find(b => b.innerText.includes(buttonText));
    if (!button) return false;
    button.click();
    return true;
}, text);"""
src=dom+"\n"+module.NOTIFY_BEFORE+"\nconst button = this.page.locator('button', { hasText: new RegExp(text, 'i') }).first();"
out=module.patched_source(src)
assert "GOOGLE_MEET_TRUSTED_JOIN_PATCH" in out
assert "const clickedByDomText = false" in out
assert "button.click()" not in out
assert "this.page.locator('button', { hasText" in out
assert "const knockConfirmed = await this.page.waitForFunction" in out
assert "if (knockConfirmed) {\n                        await notifyBeOnMeetWaitingForAdmission();" in out
assert "if (askStillVisible)" in out
assert "throw new Error('Google Meet guest join request was not accepted')" in out
assert out.count("await notifyBeOnMeetWaitingForAdmission();") == 1
for unexpected in (out,src.replace("button.click()", "return false"),src.replace(module.NOTIFY_BEFORE,"")):
    try: module.patched_source(unexpected)
    except ValueError:pass
    else:raise AssertionError("Expected fail-closed patch rejection")
print("MEET_TRUSTED_CLICK_AND_KNOCK_CONFIRMATION_TEST_PASS")
