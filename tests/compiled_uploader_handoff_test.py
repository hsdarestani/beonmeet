#!/usr/bin/env python3
"""Deployed CommonJS uploader patch must retain source without durable receipt."""
import importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('compiled_uploader',root/'patches/patch_compiled_uploader_handoff.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
source='\n'.join((mod.INIT,mod.FOLDER,mod.FILE,mod.UPLOAD,mod.FILENAME,mod.SEND_START,mod.SEND_END))
fixed=mod.patched_source(source)
assert mod.MARKER in fixed
assert 'receipt.ok && (receipt.persisted || receipt.duplicate)' in fixed
assert fixed.index('this.handoffAccepted = true;') < fixed.index('await fs_1.default.promises.unlink(filePath);')
assert 'attempt < 4' in fixed and 'AbortSignal.timeout(300000)' in fixed
assert 'String(this.botId).replace' in fixed
assert 'String(this.tempFileId).replace' in fixed
for sample in (fixed,source.replace(mod.FOLDER,'missing')):
    try:mod.patched_source(sample)
    except ValueError:pass
    else:raise AssertionError('unexpected source must fail closed')
print('COMPILED_UPLOADER_DURABLE_HANDOFF_TEST_PASS')
