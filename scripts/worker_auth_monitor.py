#!/usr/bin/env python3
"""Refresh authentication evidence on idle persistent browser profiles."""
from contextlib import ExitStack
import fcntl
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request
ROOT=pathlib.Path('/opt/beonmeet')
PORTS=(9126,9132,9133,9134,9135)
RUNTIME=ROOT/'.five-isolated-runtime'
AUTH_LINKS=RUNTIME/'qa_meet_links.json'
PROBE=ROOT/'scripts/probe_recorder_auth.js'
REFRESH_AFTER = 120
RETRY_AFTER = 30
REAUTH_RECHECK_AFTER = 120

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
    values = config()
    status_path = pathlib.Path(values.get("WORKER_AUTH_STATE_FILE") or
                               (values.get("BEONMEET_DATA_DIR") or str(ROOT / "data")) + "/worker-auth-readiness.json")
    try:
        old = json.loads(status_path.read_text())
    except (OSError, ValueError):
        old = {}
    previous = old.get("workers") or {}
    workers = {}
    due = []
    now = int(time.time())
    status_path.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as leases:
        for port in PORTS:
            key = f"http://127.0.0.1:{port}"
            row = previous.get(key) or {}
            checked = int(row.get("checked_at") or 0)
            verified = int(row.get("last_verified_at") or (checked if row.get("ready") is True else 0))
            verdict = str(row.get("verdict") or ("verified" if row.get("ready") is True else "inconclusive"))
            row = workers[key] = {
                "status": verdict,
                "verdict": verdict,
                "reason": str(row.get("reason") or "no_current_proof"),
                "ready": verdict == "verified",
                "checked_at": checked,
                "last_verified_at": verified,
                "verdict_since": int(row.get("verdict_since") or checked),
                "running_jobs": None,
            }
            filename = status_path.with_name(f"worker-auth-{port}.lock")
            with ExitStack() as lane:
                descriptor = lane.enter_context(filename.open("ab"))
                os.fchmod(descriptor.fileno(), 0o644)
                try:
                    fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    row.update(status="busy")
                    continue
                try:
                    cap = capacity(port)
                    row["running_jobs"] = int(cap["runningJobs"])
                    busy = row["running_jobs"] > 0 or int(cap["availableSlots"]) <= 0
                except (OSError, ValueError, KeyError, TypeError):
                    row.update(status="unavailable", ready=False, reason="worker_capacity_unreachable")
                    continue
                if busy:
                    row.update(status="busy")
                    continue
                age = now - checked
                interval = {
                    "verified": REFRESH_AFTER,
                    "reauthentication_required": REAUTH_RECHECK_AFTER,
                }.get(verdict, RETRY_AFTER)
                if 0 <= age < interval:
                    continue
                row.update(status="checking", ready=False)
                due.append(port)
                leases.enter_context(lane.pop_all())

        last_repair = int(old.get("last_repair_at") or 0)
        atomic_write(status_path, {"workers": workers, "last_repair_at": last_repair})
        if due:
            try:
                result = run_node(PROBE, due)
                scan = json.loads(result.stdout) if result.returncode == 0 else {}
            except (ValueError, OSError, subprocess.TimeoutExpired):
                scan = {}
            for port in due:
                key = f"http://127.0.0.1:{port}"
                row = workers[key]
                proof = (scan.get("workers") or {}).get(key) or {}
                finished = int(time.time())
                checked = int(proof.get("checked_at") or 0)
                status = proof.get("status")
                if status not in {"verified", "inconclusive", "unavailable", "reauthentication_required"} or not 0 <= finished - checked <= 165:
                    status, checked = "inconclusive", finished
                    proof = {"reason": "probe_no_valid_result"}
                if row["verdict"] != status:
                    row["verdict_since"] = checked
                row.update(status=status, verdict=status, ready=status == "verified", checked_at=checked,
                           reason=proof.get("reason"))
                if status == "verified":
                    row["last_verified_at"] = checked
            atomic_write(status_path, {"workers": workers, "last_repair_at": last_repair})

    totals = {status: sum(row["status"] == status for row in workers.values())
              for status in ("verified", "busy", "inconclusive", "unavailable", "reauthentication_required")}
    print("AUTH_WATCH_STATUS", json.dumps(totals, sort_keys=True), "probed", len(due), flush=True)

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
