#!/usr/bin/env python3
"""Real Google Meet one-lane QA without touching production billing or Telegram."""
import fcntl, json, os, pathlib, shutil, subprocess, sys, tempfile, time, uuid, urllib.request
ROOT=pathlib.Path('/opt/beonmeet')
LANE=2
PORT=9142
SINK_PORT=9190
DIR=None
CREATED=[]
def docker(*args):
 p=subprocess.run(['docker']+list(args),capture_output=True,text=True,timeout=50)
 if p.returncode:raise RuntimeError('docker '+args[0]+' '+str(p.returncode)+' '+p.stderr[:170])
 return p.stdout.strip()
def get(url):
 with urllib.request.urlopen(url,timeout=7) as r:return json.load(r)
def guard():
 h=get('http://127.0.0.1:8109/health')
 assert h.get('ok')
 for key in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
  assert not int(h.get(key) or 0), 'USER_WORK_PRESENT'
 for p in (9126,9132,9133,9134,9135):
  d=get(f'http://127.0.0.1:{p}/capacity')
  assert not int((d.get('data') or d).get('runningJobs') or 0), 'PRODUCTION_WORKER_BUSY'
 for name in ('camcam-shared-api-1','camcam-shared-pet-1',
              'camcam-shared-archive-1','camcam-shared-petarchive-1'):
  assert docker('inspect','-f','{{.State.Health.Status}}',name)=='healthy'
def canary(sink_script):
 global DIR
 guard()
 links=json.loads((ROOT/'.five-isolated-runtime/qa_meet_links.json').read_text())['links']
 assert len(links)==5 and len(set(links))==5
 assert (ROOT/'.five-isolated-runtime/worker-2.env').is_file()
 workerinfo=json.loads(docker('inspect','beonmeet-worker-five'))[0]
 overlay=next(m['Source'] for m in workerinfo['Mounts']
              if m['Destination']=='/usr/src/app/dist/bots/GoogleMeetBot.js')
 assert pathlib.Path(overlay).is_file()
 names=set(docker('ps','-a','--format','{{.Names}}').splitlines())
 assert 'beonmeet-qa-sink' not in names and 'beonmeet-qa-worker-2' not in names
 DIR=pathlib.Path(tempfile.mkdtemp(prefix='.five-real-qa-',dir=ROOT))
 os.chmod(DIR,0o700)
 os.chown(DIR,1001,1001)
 docker('run','-d','--name','beonmeet-qa-sink','--network','beonmeet-single',
        '--memory=300m','--cpus=.25','--pids-limit=90',
        '-p',f'127.0.0.1:{SINK_PORT}:3030',
        '-v',f'{sink_script}:/qa-sink.js:ro','-v',f'{DIR}:/qa',
        '--entrypoint','node','beonmeet-worker-audiofix:latest','/qa-sink.js')
 CREATED.append('beonmeet-qa-sink')
 for _ in range(20):
  try:
   if get(f'http://127.0.0.1:{SINK_PORT}/health').get('ok'):break
  except Exception:pass
  time.sleep(2)
 else:raise RuntimeError('QA callback sink not ready')
 urls=['CONTROLLER_STREAM_UPLOAD_URL','CONTROLLER_UPLOAD_URL',
       'CONTROLLER_RECORDING_STARTED_URL','CONTROLLER_WAITING_FOR_ADMISSION_URL']
 overrides=[
    '-e','CONTROLLER_STREAM_UPLOAD_URL=http://beonmeet-qa-sink:3030/internal/recording-upload',
    '-e','CONTROLLER_UPLOAD_URL=http://beonmeet-qa-sink:3030/internal/recording-ready',
    '-e','CONTROLLER_RECORDING_STARTED_URL=http://beonmeet-qa-sink:3030/internal/recording-started',
    '-e','CONTROLLER_WAITING_FOR_ADMISSION_URL=http://beonmeet-qa-sink:3030/internal/waiting-for-admission',
    '-e','MAX_RECORDING_DURATION_MINUTES=4',
    '-e','JOIN_WAIT_TIME_MINUTES=3',
    '-e','MEETING_INACTIVITY_MINUTES=1',
    '-e','INACTIVITY_DETECTION_START_DELAY_MINUTES=2',
    '-e','LONE_PARTICIPANT_EXIT_DELAY_SECONDS=120',
 ]
 docker('run','-d','--name','beonmeet-qa-worker-2','--network','beonmeet-single',
        '--memory=1200m','--memory-swap=1400m','--cpus=.75','--pids-limit=350',
        '-p',f'127.0.0.1:{PORT}:3000',
        '--env-file',str(ROOT/'.five-isolated-runtime/worker-2.env'),
        *overrides,
        '-v','/dev/shm/beonmeet:/recordings',
        '-v',f'{overlay}:/usr/src/app/dist/bots/GoogleMeetBot.js:ro',
        'beonmeet-worker-audiofix:latest')
 CREATED.append('beonmeet-qa-worker-2')
 for _ in range(22):
  try:
   d=get(f'http://127.0.0.1:{PORT}/capacity');d=d.get('data') or d
   if int(d.get('availableSlots') or 0)==1:break
  except Exception:pass
  time.sleep(2)
 else:raise RuntimeError('QA worker not ready')
 env=dict(s.split('=',1) for s in json.loads(docker('inspect','beonmeet-qa-worker-2'))[0]['Config']['Env'] if '=' in s)
 for k in urls:assert 'beonmeet-qa-sink' in env.get(k,''), k+' misconfigured'
 assert env.get('MAX_CONCURRENT_MEETINGS')=='1'
 assert env.get('GOOGLE_CHROME_CDP_URL')=='http://beonmeet-isolated-chrome-2:9223'
 print('REAL_MEET_CANARY_PRIVATE_CALLBACK_ROUTING_VERIFIED',flush=True)
 guard()
 event='beonmeet-qa-'+uuid.uuid4().hex
 payload={'bearerToken':'beonmeet-local','url':links[0],'name':'BeOnMeet QA',
          'teamId':'beonmeet-qa','timezone':'UTC','userId':'qa_lane_2',
          'eventId':event,'botId':event}
 req=urllib.request.Request(f'http://127.0.0.1:{PORT}/google/join',
                            data=json.dumps(payload).encode(),method='POST',
                            headers={'content-type':'application/json'})
 with urllib.request.urlopen(req,timeout=35) as r:
  assert r.status==202,'Worker did not accept test join'
 print('REAL_MEET_CANARY_WORKER_ACCEPTED_JOB',flush=True)
 started=False;uploaded=False
 for i in range(44):
  guard()
  sink=get(f'http://127.0.0.1:{SINK_PORT}/health')
  if int(sink.get('start') or 0)>=1 and not started:
   started=True
   print('REAL_MEET_CANARY_GOOGLE_MEET_RECORDING_STARTED',flush=True)
  if int(sink.get('uploaded') or 0)>=1:
   uploaded=True
   print('REAL_MEET_CANARY_RECORDING_UPLOAD_RECEIVED',flush=True)
   break
  if i%6==0:print('REAL_MEET_CANARY_MONITOR',i,'started',started,'admission_waits',sink.get('waiting'),'uploaded',sink.get('uploaded'),flush=True)
  time.sleep(10)
 assert started,'Google Meet recording never reached started callback'
 assert uploaded,'Google Meet recording not delivered before test timeout'
 output=DIR/'qa-lane-2-recording.webm'
 assert output.is_file() and output.stat().st_size>400000
 meta=json.loads(subprocess.check_output(
    ['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)],
    text=True,timeout=25))
 kinds={s['codec_type'] for s in meta['streams']}
 assert 'audio' in kinds and 'video' in kinds
 duration=float(meta['format'].get('duration') or 0)
 assert duration>=30,'Recording too short'
 print('REAL_MEET_CANARY_FILE_VERIFIED',round(duration,1),'seconds',output.stat().st_size,'bytes',flush=True)
 summary={'ok':True,'duration_seconds':round(duration,1),
          'size_bytes':output.stat().st_size,'streams':sorted(kinds)}
 (ROOT/'.five-isolated-runtime/qa_one_real_meet_pass.json').write_text(json.dumps(summary))
 print('REAL_MEET_ONE_LANE_E2E_PASS_NO_BILLING_NO_TELEGRAM',flush=True)

def cleanup():
 for name in reversed(CREATED):
  subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=35)
 # Delete only known QA scratch; never user recordings or source Chrome profile.
 if DIR:
  try:
   shutil.rmtree(DIR)
  except Exception:
   print('REAL_MEET_QA_SCRATCH_REQUIRES_MANUAL_CLEANUP',flush=True)

if __name__=='__main__':
 assert len(sys.argv)==2 and pathlib.Path(sys.argv[1]).is_file()
 with pathlib.Path('/var/lock/pars-vds-bot-deploy.lock').open('a') as l:
  fcntl.flock(l,fcntl.LOCK_EX)
  try:canary(pathlib.Path(sys.argv[1]))
  except Exception as e:
   print('REAL_MEET_ONE_LANE_QA_BLOCKED',type(e).__name__,str(e)[:230],flush=True)
   sys.exit(1)
  finally:cleanup()
