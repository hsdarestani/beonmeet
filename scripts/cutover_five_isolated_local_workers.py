#!/usr/bin/env python3
"""Idle-only promotion of 5 independent local Chrome/worker lanes with rollback.

This script must be invoked only after actual browser/Meet QA. It never raises
a single-Chrome concurrency guard; each of five independent endpoints gets 1.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path("/opt/beonmeet")
ENV=ROOT/".env"
PORTS=[9126,9132,9133,9134,9135]
CONTROLLER="beonmeet-controller"
CHROMES=["beonmeet-chrome-single"]+[f"beonmeet-isolated-chrome-{n}" for n in range(2,6)]
BACKUP=None

def cmd(*argv):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=25)
    if p.returncode:
        raise RuntimeError("service operation failed: "+str(argv[:3])+" code "+str(p.returncode))
    return p.stdout.strip()

def jsonurl(url):
    with urllib.request.urlopen(url,timeout=7) as r:return json.load(r)

def ready():
    h=jsonurl("http://127.0.0.1:8109/health")
    if not h.get("ok"):return False
    if any(int(h.get(k) or 0)!=0 for k in ("free_queue","premium_queue","active_delivery_jobs","pending_delivery_jobs")):
        return False
    for p in PORTS:
        d=jsonurl(f"http://127.0.0.1:{p}/capacity")
        d=d.get("data") or d
        if int(d.get("runningJobs") or 0)>0:return False
        if int(d.get("availableSlots") or 0)<1:return False
    for n in CHROMES:
        if not json.loads(cmd("docker","inspect","-f","{{json .State.Running}}",n)):
            return False
    for n in ("camcam-shared-api-1","camcam-shared-pet-1",
              "camcam-shared-archive-1","camcam-shared-petarchive-1"):
        if cmd("docker","inspect","-f","{{.State.Health.Status}}",n)!="healthy":return False
    return True

def atomic_write(contents):
    st=ENV.stat()
    fd,name=tempfile.mkstemp(prefix=".env-five-tmp-",dir=str(ROOT))
    try:
        os.fchmod(fd,stat.S_IMODE(st.st_mode))
        os.fchown(fd,st.st_uid,st.st_gid)
        with os.fdopen(fd,"w") as f:
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,ENV)
    finally:
        if Path(name).exists():os.unlink(name)

def update_lines(original):
    desired={
        "FREE_WORKER_URLS":",".join(f"http://127.0.0.1:{p}" for p in PORTS),
        "PREMIUM_WORKER_URLS":",".join(f"http://127.0.0.1:{p}" for p in PORTS),
        "FREE_MEETING_BOT_URL":"http://127.0.0.1:9126",
        "PREMIUM_MEETING_BOT_URL":"http://127.0.0.1:9126",
        "FREE_MEETING_SLOTS":"5",
        "PREMIUM_MEETING_SLOTS":"0",
        "SHARED_CHROME_MAX_ACTIVE":"1",
        "AUTOSCALE_ENABLED":"false",
    }
    original_lines=original.splitlines()
    present={}
    for l in original_lines:
        if "=" in l and not l.startswith("#"):
            k,v=l.split("=",1)
            present[k]=v
    assert present.get("FREE_WORKER_URLS")=="http://127.0.0.1:9126"
    assert present.get("PREMIUM_WORKER_URLS")=="http://127.0.0.1:9126"
    assert present.get("AUTOSCALE_ENABLED")=="false"
    assert present.get("SHARED_CHROME_MAX_ACTIVE","1") in ("1","")
    out=[]
    for line in original_lines:
        key=line.split("=",1)[0] if "=" in line and not line.startswith("#") else None
        if key in desired:
            out.append(key+"="+desired.pop(key))
        else:out.append(line)
    out.extend(k+"="+v for k,v in desired.items())
    new="\n".join(out)+"\n"
    assert len(new.splitlines())>=len(original_lines)
    assert new.count("FREE_WORKER_URLS=")==1
    assert new.count("SHARED_CHROME_MAX_ACTIVE=")==1
    return new

def main():
    global BACKUP
    assert (ROOT/".five-isolated-runtime").is_dir(), "Four standby lanes missing"
    assert (os.cpu_count() or 0)>=7
    mem=int(next(s.split()[1] for s in Path("/proc/meminfo").read_text().splitlines() if s.startswith("MemAvailable:")))
    assert mem>=9*1024*1024, "Memory headroom too small"
    assert ready(), "Production live, recording active or lane unhealthy"
    original=ENV.read_text()
    modified=update_lines(original)
    backup_dir=ROOT/(".five-isolated-cutover-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime()))
    backup_dir.mkdir(mode=0o700)
    BACKUP=backup_dir/"original.env"
    shutil.copy2(ENV,BACKUP)
    try:
        assert ready(), "New job arrived; cutover refused"
        atomic_write(modified)
        cmd("systemctl","restart",CONTROLLER)
        passed=False
        for n in range(28):
            try:
                h=jsonurl("http://127.0.0.1:8109/health")
                if h.get("ok") and int(h.get("free_worker_endpoints") or 0)==5 and int(h.get("premium_worker_endpoints") or 0)==5 and int(h.get("max_concurrent_meetings") or 0)==5:
                    passed=True;break
            except Exception:pass
            time.sleep(2)
        if not passed:raise RuntimeError("Controller did not expose five independent endpoints")
        if not ready():raise RuntimeError("Five worker or CamCam health post-cutover failed")
        for n in range(20):
            h=jsonurl("http://127.0.0.1:8109/health")
            if int(h.get("healthy_free_workers") or 0)==5:break
            time.sleep(2)
        assert int(h.get("healthy_free_workers") or 0)==5
        assert jsonurl("https://beonmeet.smarbiz.sbs/health").get("ok")
        print("FIVE_ISOLATED_CONTROLLER_CUTOVER_SUCCESS",flush=True)
        print("FIVE_ISOLATED_FIVE_DISTINCT_ENDPOINTS_CONFIRMED",flush=True)
        print("FIVE_ISOLATED_CONTROLLER_SINGLE_CHROME_GUARD_REMAINS_ONE_PER_WORKER",flush=True)
        print("FIVE_ISOLATED_E2E_ONE_HOUR_MEET_STILL_REQUIRES_SEPARATE_ACCEPTANCE",flush=True)
    except Exception as e:
        print("FIVE_ISOLATED_CUTOVER_ROLLBACK_TRIGGER",type(e).__name__,str(e)[:250],flush=True)
        atomic_write(original)
        cmd("systemctl","restart",CONTROLLER)
        for _ in range(25):
            try:
                h=jsonurl("http://127.0.0.1:8109/health")
                if h.get("ok") and int(h.get("free_worker_endpoints") or 0)==1:break
            except Exception:pass
            time.sleep(2)
        print("FIVE_ISOLATED_CUTOVER_ORIGINAL_CONTROLLER_RESTORED",flush=True)
        raise

if __name__=="__main__":
    with Path("/var/lock/pars-vds-bot-deploy.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:main()
        except Exception as e:
            print("FIVE_ISOLATED_CUTOVER_FAILED",type(e).__name__,str(e)[:280],flush=True)
            sys.exit(1)
