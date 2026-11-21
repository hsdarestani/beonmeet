#!/usr/bin/env python3
"""Regression: no Node process.env access from the serialized Meet page.evaluate body."""
from pathlib import Path
import importlib.util
import subprocess

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("quality_fix",root/"patches/patch_browser_quality_context.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sample = ("async function test() {\n"
          +mod.SIG_OLD+"\n"
          +"  "+mod.QUALITY_OLD+"\n"
          +"  const recordingQuality = qualityName;\n"
          +"},"+" {\n"
          +mod.ARGS_OLD+"\n"
          +"}\n")
patched=mod.patched_source(sample)
assert mod.MARKER in patched
assert "mimeTypes, captureQuality })" in patched
assert patched.count("captureQuality: process.env.BEONMEET_CAPTURE_QUALITY") == 1
assert "String(process.env.BEONMEET_CAPTURE_QUALITY" not in patched
assert "String(captureQuality || 'balanced')" in patched
try:mod.patched_source(patched)
except ValueError:pass
else:raise AssertionError("Repeat patch should fail closed")
for broken in (sample.replace(mod.SIG_OLD,"unexpected signature"),sample.replace(mod.QUALITY_OLD,"other quality"),sample.replace(mod.ARGS_OLD,"other args")):
    try:mod.patched_source(broken)
    except ValueError:pass
    else:raise AssertionError("Unknown source should fail closed")
# Execute the quality selection in a JS sandbox with intentionally NO 'process'.
js=r"""
const vm=require('vm');
const src=(async ({captureQuality}) => {
  const qualityName=String(captureQuality || 'balanced').toLowerCase();
  return qualityName === 'high'
    ? {width:1280,height:720,fps:15,maxFps:15,video:1200000,audio:96000}
    : qualityName === 'low'
      ? {width:640,height:360,fps:8,maxFps:10,video:320000,audio:64000}
      : {width:854,height:480,fps:10,maxFps:12,video:650000,audio:96000};
}).toString();
const choose=vm.runInNewContext('('+src+')',{});
(async()=>{
  const expected={low:[640,360],balanced:[854,480],high:[1280,720]};
  for(const [quality,dims] of Object.entries(expected)) {
    const result=await choose({captureQuality:quality});
    if(result.width!==dims[0]||result.height!==dims[1])throw Error('bad '+quality);
  }
  const fallback=await choose({});
  if(fallback.width!==854)throw Error('bad fallback');
  console.log('BROWSER_CONTEXT_NO_PROCESS_QUALITY_MODES_PASS');
})().catch(e=>{console.error(e);process.exit(1);});
"""
p=subprocess.run(["node","-e",js],capture_output=True,text=True,timeout=10)
assert p.returncode==0,(p.stderr or p.stdout)[:1200]
print(p.stdout.strip())
print("MEET_BROWSER_CAPTURE_QUALITY_CONTEXT_TEST_PASS")
