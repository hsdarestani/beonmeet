#!/usr/bin/env python3
"""One bounded recovery attempt using the existing owner account, on idle lanes only.
Run with the same exclusive host lock as the watchdog. No controller restart,
no writes to unselected browser profiles, no credentials in logs.
"""
import json, os, pathlib, subprocess, time, urllib.request
import worker_auth_monitor as watch

def select(ports, workers, capacities, now):
    idle=[p for p in ports if capacities[p].get('runningJobs')==0 and int(capacities[p].get('availableSlots') or 0)>0]
    def entry(p): return workers.get('http://127.0.0.1:'+str(p),{})
    def fresh(p):
        v=entry(p)
        return v.get('ready') is True and 0<=now-int(v.get('checked_at') or 0)<=360
    targets=[p for p in idle if not fresh(p)]
    sources=[p for p in idle if fresh(p)]
    if not targets:return []
    # Leave other healthy lanes available for dispatch; reserve at most one source.
    # With no fresh source, stale positives may still be proven by the local probe.
    return ([sources[0]] if sources else [])+targets

def get_health():
    with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=5) as r:return json.load(r)

def main():
    root=watch.ROOT
    state=pathlib.Path('/opt/beonmeet/data/worker-auth-readiness.json')
    old=json.loads(state.read_text())
    h=get_health()
    assert h['ok'] and h['auth_guard_enabled'] and h['free_worker_endpoints']==5
    assert len(old['workers'])==5
    now=int(time.time())
    caps={p:watch.capacity(p) for p in watch.PORTS}
    assert all('runningJobs' in c and 'availableSlots' in c for c in caps.values())
    chosen=select(watch.PORTS,old['workers'],caps,now)
    print('SELECTIVE_BEFORE',json.dumps({k:h.get(k) for k in ('max_concurrent_meetings','authenticated_free_workers','premium_queue','free_queue')}),flush=True)
    print('SELECTIVE_IDLE_PORTS',[p for p,c in caps.items() if c['runningJobs']==0],flush=True)
    print('SELECTIVE_CHOSEN',chosen,flush=True)
    if len(chosen)<2:
        print('SELECTIVE_SKIP_NO_SAFE_SOURCE_OR_TARGET',flush=True)
        return
    def key(p):return 'http://127.0.0.1:'+str(p)
    workers=dict(old['workers'])
    for p in chosen:workers[key(p)]={'ready':False,'checked_at':now}
    watch.atomic_write(state,{**old,'workers':workers})
    # A dispatch may already be in flight. Let it settle before touching a browser.
    time.sleep(35)
    if any(watch.capacity(p).get('runningJobs')!=0 for p in chosen):
        watch.atomic_write(state,old)
        print('SELECTIVE_ABORT_IN_FLIGHT_RECORDING',flush=True)
        return
    script=root/'scripts/recover_selected_recorder_sessions.js'
    ids=','.join(str(watch.PORTS.index(p)+1) for p in chosen)
    cmd=['docker','run','--rm','--user','0','--network','beonmeet-single','--memory=620m','--cpus=.6','--pids-limit=185','-e','NODE_PATH=/usr/src/app/node_modules','-e','BEONMEET_RECOVERY_LANES='+ids,'-v',str(script)+':/auth-script.js:ro','-v',str(watch.AUTH_LINKS)+':/qa-existing-links.json:ro','--entrypoint','node','beonmeet-worker-audiofix:latest','/auth-script.js']
    try:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=320)
        for line in p.stdout.splitlines():
            if line.startswith(('RECORDER_AUTH_SCAN_LANE ','RECORDER_AUTH_SOURCE_LANE ','RECORDER_AUTH_LANE_RECOVERED ','RECORDER_AUTH_LANE_NEEDS_OWNER_LOGIN ','RECORDER_AUTH_LANE_FINAL ','RECORDER_AUTH_SELECTED_LANES_RECHECKED')):
                print(line,flush=True)
        print('SELECTIVE_RECOVERY_EXIT',p.returncode,flush=True)
    except subprocess.TimeoutExpired:
        print('SELECTIVE_RECOVERY_TIMEOUT',flush=True)
    idle=[p for p in chosen if watch.capacity(p).get('runningJobs')==0]
    try:
        result=watch.run_node(watch.PROBE,idle) if idle else None
        scan=json.loads(result.stdout) if result and result.returncode==0 else {}
    except (ValueError,OSError,subprocess.TimeoutExpired):
        scan={}
    now=int(time.time())
    for p in chosen:
        row=(scan.get('workers') or {}).get(key(p),{})
        checked=int(row.get('checked_at') or 0)
        ready=p in idle and row.get('ready') is True and 0<=now-checked<=165
        workers[key(p)]={'ready':ready,'checked_at':checked if ready else now}
        print('SELECTIVE_VERIFIED',p,ready,flush=True)
    watch.atomic_write(state,{**old,'workers':workers,'last_repair_at':now})
    h=get_health()
    print('SELECTIVE_FINAL',json.dumps({k:h.get(k) for k in ('max_concurrent_meetings','healthy_free_workers','authenticated_free_workers','authenticated_premium_workers','free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs')}),flush=True)
    for p in watch.PORTS:
        c=watch.capacity(p)
        print('SELECTIVE_LANE',p,'running',c.get('runningJobs'),'available',c.get('availableSlots'),flush=True)

if __name__=='__main__':main()
