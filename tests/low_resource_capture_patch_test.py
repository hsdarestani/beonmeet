#!/usr/bin/env python3
"""Static smoke test for deterministic low-resource overlay, no production changes."""
import importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('low_resource_patch',root/'patches/patch_low_resource_compiled_recorder.py')
mod=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
sample='before\n'+mod.OLD_CODEC+'\n'+mod.OLD_RECORDER+'\nafter\n'
out=mod.patched_source(sample)
assert "vp8,opus" in out
assert "videoBitsPerSecond: 320000" in out
assert "audioBitsPerSecond: 64000" in out
assert "frameRate: { ideal: 8, max: 10 }" in out
try:
    mod.patched_source(out)
except ValueError:
    pass
else:
    raise AssertionError("Never patch an already-modified worker")
assert out.startswith('before') and out.endswith('after\n')
print('LOW_RESOURCE_CAPTURE_PATCH_TEST_PASS')
