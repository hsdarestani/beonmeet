#!/usr/bin/env python3
"""Minimal-diff production patch of BeOnMeet auth-aware worker dispatch.
Preserves runtime-only site customizations and the current secure .env.
Runs only after the workflow has backed up both files and checked idleness.
"""
import os, pathlib, stat, tempfile, json, sys, py_compile, urllib.request
ROOT=pathlib.Path('/opt/beonmeet')
MAIN=ROOT/'app/main.py'
ENV=ROOT/'.env'
BLOCK=(
'WORKER_AUTH_GUARD_ENABLED = os.environ.get("WORKER_AUTH_GUARD_ENABLED", "false").strip().lower() in {"1", "true", "yes"}\n'
'WORKER_AUTH_STATE_FILE = Path(os.environ.get("WORKER_AUTH_STATE_FILE", str(DATA_DIR / "worker-auth-readiness.json")))\n'
'WORKER_AUTH_MAX_AGE_SECONDS = max(60, min(900, int(os.environ.get("WORKER_AUTH_MAX_AGE_SECONDS", "360"))))\n'
'\n'
'\n'
'def _recorder_auth_ready(base_url: str) -> bool:\n'
'    if not WORKER_AUTH_GUARD_ENABLED:\n'
'        return True\n'
'    try:\n'
'        document = json.loads(WORKER_AUTH_STATE_FILE.read_text(encoding="utf-8"))\n'
'        entry = (document.get("workers") or {}).get(base_url)\n'
'        if not isinstance(entry, dict) or entry.get("ready") is not True:\n'
'            return False\n'
'        checked_at = float(entry.get("checked_at") or 0)\n'
'        age = datetime.now(timezone.utc).timestamp() - checked_at\n'
'        return 0 <= age <= WORKER_AUTH_MAX_AGE_SECONDS\n'
'    except (OSError, ValueError, TypeError, json.JSONDecodeError):\n'
'        return False\n'
)
MARKER='SHARED_CHROME_MAX_ACTIVE = max(0, min(16, int(os.environ.get("SHARED_CHROME_MAX_ACTIVE", "1"))))'
LOOP='        for pool_name, base_url in targets:\n            # An HTTP 202 only means the worker accepted the job.'
LOOP_NEW='''        for pool_name, base_url in targets:
            if WORKER_AUTH_GUARD_ENABLED and not _recorder_auth_ready(base_url):
                # Authentication may expire while the worker's HTTP health remains 200.
                # Keep the request in the durable queue, rather than Guest / Ask to join.
                saw_busy = True
                continue
            # An HTTP 202 only means the worker accepted the job.'''
HEALTH='        "healthy_premium_workers": sum(1 for url in PREMIUM_WORKER_URLS if worker_health_cache.get(url, True)),'
HEALTH_NEW=HEALTH+'''
        "auth_guard_enabled": bool(WORKER_AUTH_GUARD_ENABLED),
        "authenticated_free_workers": sum(1 for url in FREE_WORKER_URLS if _recorder_auth_ready(url)),
        "authenticated_premium_workers": sum(1 for url in PREMIUM_WORKER_URLS if _recorder_auth_ready(url)),'''

def atomic(path,text):
    prior=path.stat()
    fd,tmp=tempfile.mkstemp(prefix='.worker-auth-patch-',dir=path.parent)
    try:
        os.fchmod(fd,stat.S_IMODE(prior.st_mode))
        os.fchown(fd,prior.st_uid,prior.st_gid)
        with os.fdopen(fd,'w') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main():
    assert MAIN.is_file() and ENV.is_file()
    with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:h=json.load(r)
    assert h.get('ok')
    for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
        assert int(h.get(k) or 0)==0,'LIVE_REQUEST_IN_PROGRESS'
    original=MAIN.read_text()
    assert original.count(MARKER)==1 and original.count(LOOP)==1 and original.count(HEALTH)==1
    assert 'WORKER_AUTH_GUARD_ENABLED' not in original,'Already patched'
    changed=original.replace(MARKER,MARKER+'\n\n'+BLOCK,1).replace(LOOP,LOOP_NEW,1).replace(HEALTH,HEALTH_NEW,1)
    compile(changed,str(MAIN),'exec')
    raw=ENV.read_text()
    assert 'WORKER_AUTH_GUARD_ENABLED=' not in raw,'Auth guard env already set'
    settings=[
     'WORKER_AUTH_GUARD_ENABLED=true',
     'WORKER_AUTH_STATE_FILE=/opt/beonmeet/data/worker-auth-readiness.json',
     'WORKER_AUTH_MAX_AGE_SECONDS=360',
    ]
    modified=raw.rstrip('\n')+'\n'+'\n'.join(settings)+'\n'
    for k in ('FREE_WORKER_URLS=','PREMIUM_WORKER_URLS=','WHISPER_MODEL='):
        if k in raw:assert k in modified
    atomic(MAIN,changed)
    atomic(ENV,modified)
    print('WORKER_AUTH_GUARD_SOURCE_AND_ENV_PATCHED_ATOMICALLY')
    print('WORKER_AUTH_GUARD_GOOGLE_SESSION_VALIDATION_REQUIRED_BEFORE_DISPATCH')
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('WORKER_AUTH_GUARD_PATCH_FAILED',type(e).__name__,str(e)[:160])
        sys.exit(1)
