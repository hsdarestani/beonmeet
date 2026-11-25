#!/usr/bin/env python3
"""Read-only metrics during owner-run production QA. No user IDs or links printed."""
import argparse, hashlib, json, pathlib, shutil, sqlite3, subprocess, time, urllib.request
ROOT=pathlib.Path('/opt/beonmeet')
PORTS=(9126,9132,9133,9134,9135)
def get(port,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path}',timeout=5) as r:return json.load(r)
def state():
    return json.loads((ROOT/'data/state.json').read_text())
def cpu():
    n=[int(x) for x in pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    return sum(n[:8]),n[3]+n[4]
def disk_io():
    rows=[x.split() for x in pathlib.Path('/proc/diskstats').read_text().splitlines()]
    physical=[r for r in rows if r[2] in ('vda','sda','nvme0n1')]
    return sum(int(r[5]) for r in physical),sum(int(r[9]) for r in physical)
def oom():
    names=['beonmeet-worker-five','beonmeet-chrome-single']+[f'beonmeet-isolated-{kind}-{i}' for kind in ('worker','chrome') for i in range(2,6)]
    p=subprocess.run(['docker','inspect','-f','{{.State.OOMKilled}} {{.RestartCount}}',*names],capture_output=True,text=True,timeout=8)
    return {'oom_killed_current':sum(x.startswith('true ') for x in p.stdout.splitlines()),'restart_count_total':sum(int(x.split()[-1]) for x in p.stdout.splitlines() if len(x.split())==2 and x.split()[-1].isdigit())}
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
        mp4=str(pathlib.Path(filename).with_suffix('.mp4')) if filename else ''
        row=conn.execute('SELECT COUNT(*), COALESCE(SUM(duration_seconds),0) FROM recordings WHERE telegram_id=? AND filename IN (?,?)',(chat,filename,mp4)).fetchone()
        debit=conn.execute('SELECT COUNT(*),COALESCE(SUM(-seconds_delta),0) FROM credit_entries WHERE reference IN (?,?)',('recording:'+chat+':'+filename,'recording:'+chat+':'+mp4)).fetchone()
    return {'recording_rows':row[0],'duration_seconds':row[1],'debit_rows':debit[0],'debited_seconds':debit[1]}
def main(seconds):
    initial=state()
    old=set().union(*(set(initial.get(k,{})) for k in ('launched_events','pending_deliveries','completed_deliveries','failed_recordings')))
    known={}; cpu_prev=cpu(); io_prev=disk_io(); started=time.monotonic(); last=started
    oom_before=oom(); peak_read=0; peak_write=0
    peak_cpu=0;peak_ram=0;peak_slots=0;five_seconds=0;lowest_disk=None
    time.sleep(10)
    while time.monotonic()-started<seconds:
        now=time.monotonic(); cur=cpu()
        pct=round(100*(1-(cur[1]-cpu_prev[1])/max(1,cur[0]-cpu_prev[0])),1)
        cpu_prev=cur
        io=disk_io(); interval=max(1,now-last)
        read_mib=max(0,io[0]-io_prev[0])*512/1048576/interval
        write_mib=max(0,io[1]-io_prev[1])*512/1048576/interval
        io_prev=io;peak_read=max(peak_read,read_mib);peak_write=max(peak_write,write_mib)
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
    print(json.dumps({'summary':{'peak_host_cpu_percent':peak_cpu,'peak_host_ram_mib':peak_ram,'peak_worker_slots':peak_slots,'approx_five_concurrent_seconds':round(five_seconds),'minimum_free_disk_mib':lowest_disk,'peak_disk_read_mib_s':round(peak_read,2),'peak_disk_write_mib_s':round(peak_write,2),'oom_before':oom_before,'oom_after':oom()}}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=2400)
    a=p.parse_args();assert 10<=a.seconds<=7200
    main(a.seconds)
