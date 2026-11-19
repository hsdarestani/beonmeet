#!/usr/bin/env python3
"""Keep the shared HamoonCloud payment-gateway patch tightly scoped."""
import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'patches/fix_hamooncloud_beonmeet_plans.py'
spec=importlib.util.spec_from_file_location('payment_patch',p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cam="app.get('/payments/camcam/start', () => !['monthly','quarterly','halfyear'].includes(plan));"
beon="app.get('/payments/beonmeet/start', () => { if (!['monthly','quarterly','halfyear'].includes(plan)) return 409; });"
verify="app.get('/payments/beonmeet/verify', () => {});"
source="prefix;"+cam+"\n"+beon+"\n"+verify+"\nfooter"
new=m.patch(source)
assert new.replace(m.NEW,m.OLD)==source
assert m.NEW in new and cam in new
assert m.patch(new)==new
for bad in ('unrecognized','app.get(\'/payments/beonmeet/start\', () => 1); '+verify):
    try:m.patch(bad)
    except ValueError:pass
    else:raise AssertionError('Unknown gateway source must fail closed')
print('HAMOONCLOUD_PAYMENT_PATCH_SCOPE_TEST_PASS')
