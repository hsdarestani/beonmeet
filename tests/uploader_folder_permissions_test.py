#!/usr/bin/env python3
"""Uploader folder ACL safety regression across generated compiled JS."""
import importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[1]
path=root/"patches/patch_compiled_uploader_permissions.py"
spec=importlib.util.spec_from_file_location("uploader_perm_patch",path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sample="prefix\n"+mod.OLD+"\nreturn instance;\n"
patched=mod.patched_source(sample)
assert patched.count("mode: 0o2770") == 1
assert patched.count("chmod(instance.folderPath(), 0o2770)") == 1
assert patched.count("mkdir(instance.folderPath()") == 1
assert patched.index("chmod(instance.folderPath()") > patched.index("mkdir(instance.folderPath()")
try:mod.patched_source(patched)
except ValueError:pass
else:raise AssertionError("Must fail when already patched")
try:mod.patched_source("compiled upstream changed")
except ValueError:pass
else:raise AssertionError("Must fail closed for unrecognized uploader version")
ts=(root/"patches/disk-uploader.ts").read_text()
assert "await fs.promises.chmod(instance.folderPath(), 0o2770)" in ts
print("UPLOADER_PER_USER_GROUP_WRITE_TEST_PASS")
