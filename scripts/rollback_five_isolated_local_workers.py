#!/usr/bin/env python3
"""Safely revert 5 isolated Worker URLs to their verified pre-cutover single URL.

Never interrupt active recording, queue, or downstream delivery. Leaves all
staged independent Chrome profiles intact; only updates controller routing.
"""
import fcntl,json,os,pathlib,shutil,stat,subprocess,sys,tempfile,time,urllib.request
ROOT=pathlib.Path('/opt/beonmeet');ENV=ROOT/'.env'
PORTS=(9126,9132,9133,9134,9135)
def g(url):
 with urllib.request.urlopen(url,timeout=7) as r:return json.load(r)
def idle():
 h=g('http://127.0.0.1:8109/health')
 assert h.get('ok')
 assert int(h.get('free_worker_endpoints') or 0)==5,'Not in 5-way mode'
 for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
  assert not int(h.get(k) or 0),'BUSY_'+k
 for p in PORTS:
  d=g(f'http://127.0.0.1:{p}/capacity');d=d.get('data') or d
  assert not int(d.get('runningJobs') or 0),'ACTIVE_RECORDING_'+str(p)
def copy_atomic(data):
 st=ENV.stat()
 fd,tmp=tempfile.mkstemp(prefix='.env-local-five-rollback-',dir=ROOT)
 try:
  os.fchmod(fd,stat.S_IMODE(st.st_mode));os.fchown(fd,st.st_uid,st.st_gid)
  with os.fdopen(fd,'w') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,ENV)
 finally:
  if pathlib.Path(tmp).exists():os.unlink(tmp)
def main():
 idle()
 folders=sorted(ROOT.glob('.five-isolated-cutover-*'),reverse=True)
 assert folders,'No recorded pre-cutover backup'
 file=folders[0]/'original.env'
 assert file.is_file(),'Pre-cutover env missing'
 original=file.read_text()
 assert 'FREE_WORKER_URLS=http://127.0.0.1:9126' in original.splitlines()
 assert 'PREMIUM_WORKER_URLS=http://127.0.0.1:9126' in original.splitlines()
 assert 'AUTOSCALE_ENABLED=false' in original.splitlines()
 before=ENV.read_text()
 assert 'FREE_WORKER_URLS=http://127.0.0.1:9126,http://127.0.0.1:9132,' in before
 idle()
 try:
  copy_atomic(original)
  subprocess.run(['systemctl','restart','beonmeet-controller'],check=True,timeout=35)
  for _ in range(25):
   try:
    h=g('http://127.0.0.1:8109/health')
    if h.get('ok') and int(h.get('free_worker_endpoints') or 0)==1:break
   except Exception:pass
   time.sleep(2)
  else:raise RuntimeError('Single worker rollback failed health check')
  assert g('https://beonmeet.smarbiz.sbs/health').get('ok')
  print('FIVE_ISOLATED_SINGLE_WORKER_ROUTING_RESTORED',flush=True)
 except Exception:
  copy_atomic(before)
  subprocess.run(['systemctl','restart','beonmeet-controller'],timeout=35)
  print('FIVE_ISOLATED_ROLLBACK_FAILED_PREVIOUS_CONFIG_REINSTATED',flush=True)
  raise
if __name__=='__main__':
 with pathlib.Path('/var/lock/pars-vds-bot-deploy.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  try:main()
  except Exception as e:
   print('FIVE_ISOLATED_ROLLBACK_BLOCKED',type(e).__name__,str(e)[:250],flush=True)
   sys.exit(1)
