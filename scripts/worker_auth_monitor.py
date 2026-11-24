#!/usr/bin/env python3
"""Safe one-shot Google Meet auth audit and conditional on-host recovery.

Used by systemd timer, never called during active recording on a lane.
Controller reads its atomic, timestamped per-worker verdict and refuses Guest
browsers. Remediation copies only the owner's own authenticated Google session
on the SAME VPS, and only when all recorder lanes are idle.
"""
import fcntl,json,os,pathlib,subprocess,tempfile,time,urllib.request,datetime,sys
ROOT=pathlib.Path('/opt/beonmeet')
PORTS=(9126,9132,9133,9134,9135)
RUNTIME=ROOT/'.five-isolated-runtime'
AUTH_LINKS=RUNTIME/'qa_meet_links.json'
PROBE=ROOT/'scripts/probe_recorder_auth.js'
REPAIR=ROOT/'scripts/recover_google_recorder_sessions_from_healthy_lane.js'

def config():
    data={}
    for s in (ROOT/'.env').read_text().splitlines():
        if '=' in s and not s.lstrip().startswith('#'):
            k,v=s.split('=',1)
            if k in ('WORKER_AUTH_STATE_FILE','BEONMEET_DATA_DIR'):data[k]=v
    return data

def capacity(port):
    with urllib.request.urlopen('http://127.0.0.1:%d/capacity'%port,timeout=6) as r:
        x=json.load(r)
    return x.get('data') or x

def atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,filename=tempfile.mkstemp(prefix='.auth-status-',dir=path.parent)
    try:
        os.fchmod(fd,0o644)
        with os.fdopen(fd,'w') as f:
            json.dump(data,f,separators=(',',':'))
            f.flush();os.fsync(f.fileno())
        os.replace(filename,path)
    finally:
        if os.path.exists(filename):os.unlink(filename)

def run_node(code,input_ports):
    assert code.is_file() and AUTH_LINKS.is_file()
    fd,filename=tempfile.mkstemp(prefix='.auth-input-',dir=RUNTIME)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'ports':input_ports},f)
        mounts=[
            '-v',f'{code}:/auth-script.js:ro',
            '-v',f'{AUTH_LINKS}:/qa-links.json:ro',
            '-v',f'{filename}:/qa-input.json:ro'
        ]
        if code==REPAIR:
            mounts=[
                '-v',f'{code}:/auth-script.js:ro',
                '-v',f'{AUTH_LINKS}:/qa-existing-links.json:ro'
            ]
        cmd=['docker','run','--rm','--user','0','--network','beonmeet-single',
             '--memory=620m','--cpus=.6','--pids-limit=185','-e',
             'NODE_PATH=/usr/src/app/node_modules',*mounts,
             '--entrypoint','node','beonmeet-worker-audiofix:latest','/auth-script.js']
        return subprocess.run(cmd,text=True,capture_output=True,timeout=225)
    finally:
        if os.path.exists(filename):os.unlink(filename)

def main():
    config_values=config()
    status_path=pathlib.Path(config_values.get('WORKER_AUTH_STATE_FILE') or
      (config_values.get('BEONMEET_DATA_DIR') or str(ROOT/'data'))+'/worker-auth-readiness.json')
    try:old=json.loads(status_path.read_text())
    except (OSError,ValueError):old={}
    before=old.get('workers') or {}
    now=int(time.time())
    workers={}
    for port in PORTS:
        key='http://127.0.0.1:'+str(port)
        existing=before.get(key) or {}
        workers[key]={
            'ready':existing.get('ready') is True,
            'checked_at':int(existing.get('checked_at') or 0)
        }
    idle=[]
    for port in PORTS:
        key='http://127.0.0.1:'+str(port)
        try:
            cap=capacity(port)
            if int(cap.get('runningJobs') or 0)==0 and int(cap.get('availableSlots') or 0)>0:
                idle.append(port)
        except Exception:
            workers[key]={'ready':False,'checked_at':now}
    if idle:
        result=run_node(PROBE,idle)
        if result.returncode==0:
            try:scan=json.loads(result.stdout)
            except ValueError:scan={}
            for port in idle:
                key='http://127.0.0.1:'+str(port)
                row=(scan.get('workers') or {}).get(key)
                if isinstance(row,dict):
                    workers[key]={'ready':row.get('ready') is True,'checked_at':now}
                else:workers[key]={'ready':False,'checked_at':now}
        else:
            for port in idle:
                workers['http://127.0.0.1:'+str(port)]={'ready':False,'checked_at':now}
            print('AUTH_WATCH_PROBE_ERROR','failure',flush=True)
    last_repair=int(old.get('last_repair_at') or 0)
    valid=sum(1 for v in workers.values() if v['ready'] and now-int(v['checked_at'])<360)
    invalid=len(workers)-valid
    # Conservative, bounded self-recovery: only with one verified source and no
    # active jobs, and no more than one attempt per 30 minutes. Shared Google
    # sessions may be rotated; do not hammer login endpoints.
    if len(idle)==5 and valid>0 and invalid>0 and now-last_repair>=1800:
        last_repair=now  # persist cooldown even if recovery fails
        atomic_write(status_path,{'workers':workers,'last_repair_at':last_repair})
        try:
            # Recheck before mutating any browser credentials.
            if all(int(capacity(p).get('runningJobs') or 0)==0 for p in PORTS):
                fix=run_node(REPAIR,[])
                if fix.returncode==0:
                    test=run_node(PROBE,list(PORTS))
                    if test.returncode==0:
                        scan=json.loads(test.stdout)
                        for port in PORTS:
                            key='http://127.0.0.1:'+str(port)
                            row=(scan.get('workers') or {}).get(key) or {}
                            workers[key]={'ready':row.get('ready') is True,'checked_at':int(time.time())}
                        print('AUTH_WATCH_ON_HOST_RECOVERY_VERIFIED',sum(v['ready'] for v in workers.values()),flush=True)
                    else:print('AUTH_WATCH_AFTER_RECOVERY_CHECK_FAILED',flush=True)
                else:print('AUTH_WATCH_RECOVERY_NOT_SUCCEEDED',flush=True)
        except (Exception,) as e:
            print('AUTH_WATCH_RECOVERY_ERROR',type(e).__name__,flush=True)
    atomic_write(status_path,{'workers':workers,'last_repair_at':last_repair})
    ready=sum(bool(v['ready']) and int(time.time())-v['checked_at']<=360 for v in workers.values())
    print('AUTH_WATCH_STATUS','verified_ready',ready,'worker_endpoints',len(workers),
          'busy_not_probed',len(PORTS)-len(idle),flush=True)

if __name__=='__main__':
    try:
        if os.environ.get('AUTH_WATCH_INSIDE_LOCKED_DEPLOY')=='1':
            # Deployment workflow already holds the exclusive VPS deploy lock.
            main()
        else:
            with pathlib.Path('/var/lock/pars-vds-bot-deploy.lock').open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    print('AUTH_WATCH_DEPLOY_LOCK_BUSY_SKIP',flush=True);sys.exit(0)
                main()
    except Exception as e:
        print('AUTH_WATCH_FATAL',type(e).__name__,flush=True)
        sys.exit(1)
