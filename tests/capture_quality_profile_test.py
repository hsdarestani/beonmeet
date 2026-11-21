#!/usr/bin/env python3
"""Validate safe capture quality modes without altering a live recorder."""
from pathlib import Path
import importlib.util
import ast

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(obj)
    return obj

low=module("low_resource",ROOT/"patches/patch_low_resource_compiled_recorder.py")
quality=module("capture_quality",ROOT/"patches/patch_capture_quality_profile.py")
base=quality.SIG_OLD+"\n"+low.OLD_CODEC+"\n"+low.OLD_RECORDER+"\n"+quality.ARGS_OLD+"\n"
prepared=low.patched_source(base)
assert prepared.count(quality.OLD)==1, "Overlay must match deployed 360p patch"
upgraded=quality.patched_source(prepared)
assert "BEONMEET_CAPTURE_QUALITY" in upgraded
assert "String(process.env.BEONMEET_CAPTURE_QUALITY" not in upgraded
assert "String(captureQuality || 'balanced')" in upgraded
assert "captureQuality: process.env.BEONMEET_CAPTURE_QUALITY" in upgraded
assert "width: 854, height: 480" in upgraded
assert "width: 1280, height: 720" in upgraded
assert "width: 640, height: 360" in upgraded
assert "video: 650000, audio: 96000" in upgraded
assert "video: 1200000, audio: 96000" in upgraded
assert "video: 320000, audio: 64000" in upgraded
assert upgraded.count("new MediaRecorder(stream") == 1
for source in (upgraded, "unexpected worker"):
    try:
        quality.patched_source(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Must reject already-modified/unknown source")
print("CAPTURE_QUALITY_PROFILE_TEST_PASS")
