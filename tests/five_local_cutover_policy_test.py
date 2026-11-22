"""Prevent accidental multi-session sharing of any one Chrome after local cutover."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'scripts/cutover_five_isolated_local_workers.py'
spec=importlib.util.spec_from_file_location('five_local_cutover',P)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original=(
    'GOOGLE_CLIENT_SECRET=dummy-sensitive-unmodified\n'
    'FREE_WORKER_URLS=http://127.0.0.1:9126\n'
    'PREMIUM_WORKER_URLS=http://127.0.0.1:9126\n'
    'FREE_MEETING_SLOTS=5\n'
    'PREMIUM_MEETING_SLOTS=0\n'
    'AUTOSCALE_ENABLED=false\n'
    'WHISPER_MODEL=large-v3-turbo\n'
)
updated=module.update_lines(original)
v=dict(line.split('=',1) for line in updated.splitlines() if '=' in line)
expected=['http://127.0.0.1:9126']+[f'http://127.0.0.1:{p}' for p in range(9132,9136)]
assert v['FREE_WORKER_URLS'].split(',')==expected
assert v['PREMIUM_WORKER_URLS'].split(',')==expected
assert v['SHARED_CHROME_MAX_ACTIVE']=='1'
assert v['FREE_MEETING_SLOTS']=='5'
assert v['PREMIUM_MEETING_SLOTS']=='0'
assert v['AUTOSCALE_ENABLED']=='false'
assert v['GOOGLE_CLIENT_SECRET']=='dummy-sensitive-unmodified'
assert v['WHISPER_MODEL']=='large-v3-turbo'
try:
    module.update_lines(updated)
except AssertionError:
    pass
else:raise AssertionError('Cutover must refuse repeated/reentrant promotion')
print('FIVE_LOCAL_WORKER_CUTOVER_POLICY_TEST_PASS')
