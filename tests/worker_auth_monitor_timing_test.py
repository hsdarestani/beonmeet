#!/usr/bin/env python3
"""Regression tests for watchdog timing, busy-lane protection and fail-closed behavior."""
import importlib.util,json,pathlib,tempfile,types
from unittest.mock import patch
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('watch',root/'scripts/worker_auth_monitor.py')
watch=importlib.util.module_from_spec(spec);spec.loader.exec_module(watch)
with tempfile.TemporaryDirectory() as tmp:
    status=pathlib.Path(tmp)/'status.json'
    ports=watch.PORTS
    def key(p):return 'http://127.0.0.1:'+str(p)
    old={key(p):{'ready':True,'checked_at':800} for p in ports}
    old[key(ports[2])]={'ready':False,'checked_at':800}
    status.write_text(json.dumps({'workers':old}))
    def cap(p):
        if p==ports[0]:return {'runningJobs':1,'availableSlots':0}
        if p==ports[4]:return {}
        return {'runningJobs':0,'availableSlots':1}
    def probe(code,due):
        assert due==list(ports[1:4]),due
        return types.SimpleNamespace(returncode=0,stdout=json.dumps({'workers':{
            key(ports[1]):{'ready':True,'checked_at':995},
            key(ports[2]):{'ready':False,'checked_at':998},
            key(ports[3]):{'ready':True,'checked_at':999},
        }}))
    with patch.object(watch,'config',return_value={'WORKER_AUTH_STATE_FILE':str(status)}),patch.object(watch,'capacity',side_effect=cap),patch.object(watch,'run_node',side_effect=probe),patch.object(watch.time,'time',return_value=1000):
        watch.main()
    result=json.loads(status.read_text())['workers']
    assert result[key(ports[0])]==old[key(ports[0])], 'busy lane must not be probed or renewed'
    assert result[key(ports[1])]=={'ready':True,'checked_at':995}
    assert result[key(ports[2])]=={'ready':False,'checked_at':998}
    assert result[key(ports[3])]=={'ready':True,'checked_at':999}
    assert result[key(ports[4])]=={'ready':False,'checked_at':1000}
    with patch.object(watch,'config',return_value={'WORKER_AUTH_STATE_FILE':str(status)}),patch.object(watch,'capacity',return_value={'runningJobs':0,'availableSlots':1}),patch.object(watch,'run_node',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(watch.time,'time',return_value=1500):
        watch.main()
    assert not any(v['ready'] for v in json.loads(status.read_text())['workers'].values())
print('AUTH_WATCHDOG_TIMING_BUSY_LANE_AND_FAIL_CLOSED_PASS')
