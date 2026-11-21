#!/usr/bin/env python3
"""Prevent false-positive Meet admission and verify new UI in-call proof."""
from pathlib import Path
import importlib.util
import json
import subprocess

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("proof",root/"patches/patch_modern_incall_proof.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
old=module.LEAVE_OLD+"\n"+module.FALLBACK_OLD+"\n"+module.PREJOIN_SCREENSHOT_OLD
new=module.patched_source(old)
assert "BEONMEET_MODERN_IN_CALL_PROOF_V1" in new
assert "data-avatar-count" in new
assert 'hasLeave && hasHand && hasChat && hasMedia' in new
assert "!hasPrejoinButton && !pendingAdmission" in new
assert 'button[aria-label*="Leave call"]' in new
assert "timeout: 1200" in new
assert "try {" in new and "catch (debugFailure)" in new
try: module.patched_source(new)
except ValueError: pass
else: raise AssertionError("Must reject repeat")
try: module.patched_source(old.replace(module.LEAVE_OLD,"unexpected"))
except ValueError: pass
else: raise AssertionError("Must fail closed if upstream code changed")

js='''const check=new Function("document","location",%s);
function probe(labels,badge,body="",host="meet.google.com"){
  const doc={
    body:{innerText:body},
    querySelectorAll:()=>labels.map(x=>({getAttribute:()=>x,innerText:x})),
    querySelector:()=>badge===null?null:{getAttribute:()=>String(badge)}
  };
  return !!check(doc,{hostname:host});
}
const full=["Leave call","Raise hand","Chat","Turn off microphone","Turn off camera"];
const tests=[
  [full,1,"","meet.google.com",true],
  [full,2,"","meet.google.com",true],
  [full,1,"Asking to join","meet.google.com",false],
  [full,1,"Waiting for someone to let you in","meet.google.com",false],
  [[...full,"Ask to join"],1,"","meet.google.com",false],
  [["Leave call"],1,"","meet.google.com",false],
  [full.filter(x=>x!=="Chat"),1,"","meet.google.com",false],
  [full.filter(x=>x!=="Raise hand"),1,"","meet.google.com",false],
  [full,0,"","meet.google.com",false],
  [full,null,"","meet.google.com",false],
  [full,1,"","workspace.google.com",false]
];
for(const [labels,badge,body,host,expected] of tests) {
  const actual=probe(labels,badge,body,host);
  if(actual!==expected)throw Error("in-call proof accepted incorrect case");
}
console.log("MEET_INCALL_POSITIVE_AND_NEGATIVE_CASES_PASS",tests.length);
''' % json.dumps(module.FALLBACK_NEW)
p=subprocess.run(["node","-e",js],text=True,capture_output=True,timeout=8)
if p.returncode: raise AssertionError((p.stderr or p.stdout)[:1400])
print(p.stdout.strip())
print("MODERN_GOOGLE_MEET_INCALL_OVERLAY_TEST_PASS")
