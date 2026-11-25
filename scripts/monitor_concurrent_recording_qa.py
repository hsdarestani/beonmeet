#!/usr/bin/env python3
"""Read-only metrics during owner-run production QA. No user IDs or links printed."""
import argparse, hashlib, json, pathlib, shutil, sqlite3, time, urllib.request
ROOT=pathlib.Path('/opt/beonmeet')
PORTS=(9126,9132,9133,9134,9135)
def get(port,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path}',timeout=5) as r:return json.load(r)
def state():
    return json.loads((ROOT/'data/state.json').read_text())
def cpu():
    n=[int(x) for x in pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    return sum(n[:8]),n[3]+n[4]
def memory():
    d={x.split(':')[0]:int(x.split()[1]) for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith(('MemTotal:','MemAvailable:'))}
    return (d['MemTotal']-d['MemAvailable'])//1024
def tag(e):return hashlib.sha256(e.encode()).hexdigest()[:12]
def billing(receipt):
    db=ROOT/'data/beonmeet.db'
    if not db.is_file():return None
    filename=receipt.get('filename','')
    chat=receipt.get('chat_id','')
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as conn:
        row=conn.execute('SELECT COUNT(*), COALESCE(SUM(duration_seconds),0) FROM recordings WHERE telegram_id=? AND filename=?',(chat,filename)).fetchone()
        debit=conn.execute('SELECT COUNT(*),COALESCE(SUM(-seconds_delta),0) FROM credit_entries WHERE reference=?',('recording:'+chat+':'+filename,)).fetchone()
    return {'recording_rows':row[0],'duration_seconds':row[1],'debit_rows':debit[0],'debited_seconds':debit[1]}
def main(seconds):
    initial=state()
    old=set().union(*(set(initial.get(k,{})) for k in ('launched_events','pending_deliveries','completed_deliveries','failed_recordings')))
    known={}; cpu_prev=cpu(); started=time.monotonic(); last=started
    peak_cpu=0;peak_ram=0;peak_slots=0;five_seconds=0;lowest_disk=None
    while time.monotonic()-started<seconds:
        now=time.monotonic(); cur=cpu()
        pct=round(100*(1-(cur[1]-cpu_prev[1])/max(1,cur[0]-cpu_prev[0])),1)
        cpu_prev=cur
        ram=memory();free=shutil.disk_usage(ROOT).free//1048576
        peak_cpu=max(peak_cpu,pct);peak_ram=max(peak_ram,ram)
        lowest_disk=free if lowest_disk is None else min(lowest_disk,free)
        try:
            h=get(8109,'health');s=state()
            counts=[]
            for p in PORTS:
                c=get(p,'capacity');counts.append(int((c.get('data') or c).get('runningJobs',0)))
            slots=sum(counts);peak_slots=max(peak_slots,slots)
            if slots==5:five_seconds+=now-last
            print(json.dumps({'elapsed_seconds':round(now-started),'cpu_percent':pct,'ram_used_mib':ram,'disk_free_mib':free,'active_slots':slots,'lane_counts':counts,'authenticated_lanes':h.get('authenticated_free_workers'),'pending_deliveries':h.get('pending_delivery_jobs'),'pending_transcription':h.get('pending_transcription_jobs')}),flush=True)
            for kind in ('launched_events','pending_deliveries','completed_deliveries','failed_recordings'):
                for eid,v in s.get(kind,{}).items():
                    if eid in old:continue
                    row={'job':tag(eid),'stage':kind,'status':v.get('status'),'attempts':v.get('attempts'),'video':v.get('video_delivered'),'audio':v.get('audio_delivered'),'transcript':v.get('transcript_delivered'),'duration_seconds':v.get('duration'),'persisted_at':v.get('persisted_at'),'video_delivered_at':v.get('video_delivered_at'),'completed_at':v.get('completed_at')}
                    fingerprint=json.dumps(row,sort_keys=True)
                    if known.get((eid,kind))!=fingerprint:
                        known[(eid,kind)]=fingerprint
                        if kind=='completed_deliveries':row['billing']=billing(v)
                        print(json.dumps({'job_transition':row}),flush=True)
        except Exception as e:print(json.dumps({'sample_error':type(e).__name__}),flush=True)
        last=now
        time.sleep(10)
    print(json.dumps({'summary':{'peak_host_cpu_percent':peak_cpu,'peak_host_ram_mib':peak_ram,'peak_worker_slots':peak_slots,'approx_five_concurrent_seconds':round(five_seconds),'minimum_free_disk_mib':lowest_disk}}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=2400)
    a=p.parse_args();assert 10<=a.seconds<=7200
    main(a.seconds)
