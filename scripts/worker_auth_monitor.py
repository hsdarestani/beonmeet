#!/usr/bin/env python3
"""Bounded, idle-only per-lane authentication checks.
Do not copy sessions between profiles: use independently authorized accounts.
The controller continues to fail closed on missing, stale or negative proof.
"""
import fcntl,json,os,pathlib,subprocess,tempfile,time,urllib.request,datetime,sys
ROOT=pathlib.Path('/opt/beonmeet')
PORTS=(9126,9132,9133,9134,9135)
RUNTIME=ROOT/'.five-isolated-runtime'
AUTH_LINKS=RUNTIME/'qa_meet_links.json'
PROBE=ROOT/'scripts/probe_recorder_auth.js'
REFRESH_AFTER=120
NEGATIVE_RETRY_AFTER=90

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
        cmd=['docker','run','--rm','--user','0','--network','beonmeet-single',
             '--memory=620m','--cpus=.6','--pids-limit=185','-e',
             'NODE_PATH=/usr/src/app/node_modules',*mounts,
             '--entrypoint','node','beonmeet-worker-audiofix:latest','/auth-script.js']
        return subprocess.run(cmd,text=True,capture_output=True,timeout=165)
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
    due=[]
    for port in PORTS:
        key='http://127.0.0.1:'+str(port)
        try:
            cap=capacity(port)
            if 'runningJobs' not in cap or 'availableSlots' not in cap:
                raise ValueError('missing capacity fields')
            if int(cap['runningJobs'])==0 and int(cap['availableSlots'])>0:
                idle.append(port)
                age=now-workers[key]['checked_at']
                threshold=REFRESH_AFTER if workers[key]['ready'] else NEGATIVE_RETRY_AFTER
                if age<0 or age>=threshold:
                    due.append(port)
        except Exception:
            workers[key]={'ready':False,'checked_at':int(time.time())}
    last_repair=int(old.get('last_repair_at') or 0)
    # Publish transport failures immediately. Never renew a cached positive
    # verdict without a successful real Google Meet probe.
    atomic_write(status_path,{'workers':workers,'last_repair_at':last_repair})
    if due:
        try:
            result=run_node(PROBE,due)
            scan=json.loads(result.stdout) if result.returncode==0 else {}
        except (ValueError,OSError,subprocess.TimeoutExpired):
            scan={}
        for port in due:
            key='http://127.0.0.1:'+str(port)
            row=(scan.get('workers') or {}).get(key)
            finished=int(time.time())
            checked=int(row.get('checked_at') or 0) if isinstance(row,dict) else 0
            # Use the actual completion timestamp for each independent lane,
            # not the start of a multi-lane scan.
            if isinstance(row,dict) and 0<=finished-checked<=165:
                workers[key]={'ready':row.get('ready') is True,'checked_at':checked}
            else:
                workers[key]={'ready':False,'checked_at':finished}
        atomic_write(status_path,{'workers':workers,'last_repair_at':last_repair})
    ready=sum(bool(v['ready']) and 0<=int(time.time())-v['checked_at']<=360 for v in workers.values())
    print('AUTH_WATCH_STATUS','verified_ready',ready,'worker_endpoints',len(workers),
          'busy_not_probed',len(PORTS)-len(idle),'probed',len(due),flush=True)
    if ready<5:
        print('AUTH_WATCH_DEGRADED','independent_owner_login_may_be_required',flush=True)

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
