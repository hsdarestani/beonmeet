#!/usr/bin/env python3
"""Concurrent five REAL Google Meet join/recording-start acceptance (90s).

Does not route customers to QA workers or invoke billable production callbacks.
Source signed-in Chrome and current CamCam services are left unchanged.
"""
import fcntl,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile,time,urllib.request,uuid
ROOT=pathlib.Path('/opt/beonmeet')
RUNTIME=ROOT/'.five-isolated-runtime'
CREATED=[]
PROFILE=ROOT/'chrome-profile-isolated-qa6'
TEMP=None

def cmd(*args):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=60)
 if p.returncode:raise RuntimeError('Command failed '+str(args[:4])+' code='+str(p.returncode))
 return p.stdout.strip()

def docker(*args):return cmd('docker',*args)

def g(url):
 with urllib.request.urlopen(url,timeout=7) as r:return json.load(r)

def c(port):d=g(f'http://127.0.0.1:{port}/capacity');return d.get('data') or d

def guard():
 h=g('http://127.0.0.1:8109/health')
 assert h.get('ok')
 for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
  assert not int(h.get(k) or 0),'PRODUCTION_BUSY'
 for p in (9126,9132,9133,9134,9135):
  assert int(c(p).get('runningJobs') or 0)==0,'ACTIVE_CUSTOMER_JOB'
 for name in ('camcam-shared-api-1','camcam-shared-pet-1','camcam-shared-archive-1','camcam-shared-petarchive-1'):
  assert docker('inspect','-f','{{.State.Health.Status}}',name)=='healthy','CAMCAM_UNHEALTHY'
 mem=int(next(line.split()[1] for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))
 assert mem>6*1024*1024,'RAM_SAFETY_ABORT'
 return round(mem/1024),float(pathlib.Path('/proc/loadavg').read_text().split()[0])

def new(name,args):
 docker('run','-d','--name',name,*args)
 CREATED.append(name)

def wait(predicate,detail):
 for _ in range(38):
  try:
   if predicate():return
  except Exception:pass
  time.sleep(2)
 raise RuntimeError('Not ready: '+detail)

def clone(source,target):
 def ignores(_dir,names):
  return {n for n in names if n.startswith('Singleton') or n in ('LOCK','Crashpad','GPUCache','ShaderCache','GrShaderCache')}
 shutil.copytree(source,target,symlinks=True,ignore=ignores)
 for rel in ('Default/Network/Cookies','Default/Cookies'):
  f=source/rel
  if f.is_file():
   with sqlite3.connect(f'file:{f}?mode=ro',uri=True,timeout=10) as x:
    with sqlite3.connect(target/rel,timeout=10) as y:x.backup(y,pages=64,sleep=.05)
 for root,dirs,files in os.walk(target,followlinks=False):
  os.chown(root,1001,1001)
  for item in files:
   path=pathlib.Path(root)/item
   if not path.is_symlink():os.chown(path,1001,1001)
 target.chmod(0o700)

def test(sink_js):
 global TEMP
 guard()
 assert not PROFILE.exists(),'QA Chrome profile already exists'
 assert RUNTIME.is_dir()
 links=json.loads((RUNTIME/'qa_meet_links.json').read_text())['links']
 assert len(links)==5 and len(set(links))==5
 names=set(docker('ps','-a','--format','{{.Names}}').splitlines())
 for name in ['beonmeet-qa-five-sink','beonmeet-isolated-chrome-6']+[f'beonmeet-qa-five-worker-{i}' for i in range(2,7)]:
  assert name not in names, 'QA container name conflict'
 assert shutil.disk_usage('/').free>20*1024**3
 assert shutil.disk_usage('/dev/shm').free>7*1024**3
 TEMP=pathlib.Path(tempfile.mkdtemp(prefix='.five-real-concurrent-qa-',dir=ROOT))
 TEMP.chmod(0o700)
 overlay=json.loads(docker('inspect','beonmeet-worker-five'))[0]
 overlay=next(m['Source'] for m in overlay['Mounts'] if m['Destination']=='/usr/src/app/dist/bots/GoogleMeetBot.js')
 assert pathlib.Path(overlay).is_file()

 clone(ROOT/'chrome-profile',PROFILE)
 new('beonmeet-isolated-chrome-6',[
  '--network','beonmeet-single','--memory=1800m','--memory-swap=2100m',
  '--cpus=1.15','--pids-limit=450','--shm-size=512m',
  '-e','CHROME_WINDOW_SIZE=1280,720',
  '-v',f'{PROFILE}:/tmp/chrome-profile',
  'beonmeet-chrome-cdp:latest'])
 wait(lambda:subprocess.run(['docker','exec','beonmeet-isolated-chrome-6',
       'curl','-fsS','--max-time','2','http://127.0.0.1:9223/json/version'],
       capture_output=True,timeout=6).returncode==0,'Chrome6')
 new('beonmeet-qa-five-sink',[
  '--network','beonmeet-single','--memory=250m','--cpus=.2','--pids-limit=120',
  '-p','127.0.0.1:9192:3031',
  '-v',f'{sink_js}:/sink.js:ro','--entrypoint','node',
  'beonmeet-worker-audiofix:latest','/sink.js'])
 wait(lambda:g('http://127.0.0.1:9192/health').get('ok'),'QA sink')

 for i in range(2,7):
  env_file=RUNTIME/f'worker-{i}.env'
  if i==6:
   src=(RUNTIME/'worker-2.env').read_text().splitlines()
   vals=[]
   for line in src:
    if line.startswith('GOOGLE_CHROME_CDP_URL='):
     line='GOOGLE_CHROME_CDP_URL=http://beonmeet-isolated-chrome-6:9223'
    vals.append(line)
   env_file=TEMP/'worker-6.env';env_file.write_text('\n'.join(vals)+'\n');env_file.chmod(0o600)
  assert env_file.is_file()
  new(f'beonmeet-qa-five-worker-{i}',[
   '--network','beonmeet-single','--memory=1150m','--memory-swap=1350m',
   '--cpus=.65','--pids-limit=350','--shm-size=256m',
   '-p',f'127.0.0.1:{9140+i}:3000',
   '--env-file',str(env_file),
   '-e','CONTROLLER_STREAM_UPLOAD_URL=http://beonmeet-qa-five-sink:3031/internal/recording-upload',
   '-e','CONTROLLER_UPLOAD_URL=http://beonmeet-qa-five-sink:3031/internal/recording-ready',
   '-e','CONTROLLER_RECORDING_STARTED_URL=http://beonmeet-qa-five-sink:3031/internal/recording-started',
   '-e','CONTROLLER_WAITING_FOR_ADMISSION_URL=http://beonmeet-qa-five-sink:3031/internal/waiting-for-admission',
   '-e','MAX_RECORDING_DURATION_MINUTES=8',
   '-e','MEETING_INACTIVITY_MINUTES=15',
   '-e','INACTIVITY_DETECTION_START_DELAY_MINUTES=15',
   '-e','LONE_PARTICIPANT_EXIT_DELAY_SECONDS=600',
   '-v','/dev/shm/beonmeet:/recordings',
   '-v',f'{overlay}:/usr/src/app/dist/bots/GoogleMeetBot.js:ro',
   'beonmeet-worker-audiofix:latest'])
  wait(lambda: int(c(9140+i).get('availableSlots') or 0)==1,f'qa worker {i}')
  env=dict(x.split('=',1) for x in json.loads(docker('inspect',f'beonmeet-qa-five-worker-{i}'))[0]['Config']['Env'] if '=' in x)
  assert env['MAX_CONCURRENT_MEETINGS']=='1'
  assert env['GOOGLE_CHROME_CDP_URL']==f'http://beonmeet-isolated-chrome-{i}:9223'
  assert all('beonmeet-qa-five-sink' in env[k] for k in (
      'CONTROLLER_STREAM_UPLOAD_URL','CONTROLLER_UPLOAD_URL','CONTROLLER_RECORDING_STARTED_URL','CONTROLLER_WAITING_FOR_ADMISSION_URL'))
 print('FIVE_REAL_QA_FIVE_WORKERS_BROWSER_ISOLATION_CONFIRMED',flush=True)
 guard()

 # Sequentially launch five actual Google Meet rooms, with no charge or chat messages.
 for i,link in enumerate(links,2):
  event='beonmeet-load-qa-'+uuid.uuid4().hex
  payload={'bearerToken':'beonmeet-local','url':link,'name':'BeOnMeet Test',
           'teamId':'beonmeet-qa','timezone':'UTC','userId':f'qa_lane_{i}',
           'eventId':event,'botId':event}
  request=urllib.request.Request(f'http://127.0.0.1:{9140+i}/google/join',
     method='POST',data=json.dumps(payload).encode(),headers={'content-type':'application/json'})
  with urllib.request.urlopen(request,timeout=35) as res:assert res.status==202
  print('FIVE_REAL_QA_MEET_JOIN_ACCEPTED',i,flush=True)
  time.sleep(3)

 # At least 60s *simultaneous* runningJobs=5 is required.
 start=time.monotonic()
 healthy_since=None
 proof=False
 while time.monotonic()-start<355:
  mem,load=guard()
  stats=g('http://127.0.0.1:9192/health')
  started=len(stats.get('started') or [])
  running=sum(1 for i in range(2,7) if int(c(9140+i).get('runningJobs') or 0)==1)
  if started==5 and running==5:
   if healthy_since is None:healthy_since=time.monotonic()
   if time.monotonic()-healthy_since>=60:
    proof=True;break
  else:healthy_since=None
  if load>18:raise RuntimeError('EXCESSIVE_LOAD')
  print('FIVE_REAL_QA_SAMPLE','started',started,'running',running,'ram_mb',mem,'load1',load,flush=True)
  time.sleep(10)
 assert proof,'Could not maintain five real Meet sessions for 60 consecutive seconds'
 guard()
 (RUNTIME/'qa_five_real_started_pass.json').write_text(json.dumps({
   'ok':True,'independent_sessions':5,'simultaneous_seconds':60,
   'class':'real_google_meet_join_not_one_hour_delivery'}))
 print('FIVE_REAL_QA_FIVE_GOOGLE_MEET_RECORDINGS_SIMULTANEOUS_60S_PASS',flush=True)

def cleanup():
 for name in reversed(CREATED):
  subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=40)
 if PROFILE.exists():shutil.rmtree(PROFILE,ignore_errors=True)
 if TEMP:shutil.rmtree(TEMP,ignore_errors=True)
 for i in range(2,7):
  folder=pathlib.Path('/dev/shm/beonmeet')/f'qa_lane_{i}'
  if folder.is_dir():shutil.rmtree(folder,ignore_errors=True)

if __name__=='__main__':
 if len(sys.argv)!=2:sys.exit(2)
 with pathlib.Path('/var/lock/pars-vds-bot-deploy.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  try:test(pathlib.Path(sys.argv[1]))
  except Exception as e:
   print('FIVE_REAL_QA_FAILED',type(e).__name__,str(e)[:260],flush=True)
   sys.exit(1)
  finally:cleanup()
