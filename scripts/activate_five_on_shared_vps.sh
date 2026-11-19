#!/usr/bin/env bash
# One-time, opt-in five-slot pilot on the EXISTING 3-vCPU/6-GiB shared VPS.
# Keeps original single-slot worker running as fallback. Changes no CamCam containers.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST;exit 1;; esac
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 45 9
cd /opt/beonmeet
TARGET=beonmeet-worker-five
test -s .env
test ! -e /opt/beonmeet/.five-slot-pilot-active
! docker ps -a --format '{{.Names}}' | grep -Fxq "$TARGET" || { echo EXISTING_FIVE_WORKER;exit 1; }
python3 - <<'PY'
from pathlib import Path
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:d=json.load(r)
assert int(d['max_concurrent_meetings'])==1, 'Expect one active recorder before promotion'
assert not d.get('autoscaler_enabled'), 'No autoscaling allowed'
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(d.get(k) or 0)==0,k+' not idle'
with urllib.request.urlopen('http://127.0.0.1:9124/capacity',timeout=8) as r:c=json.load(r)
assert int((c.get('data') or c).get('runningJobs') or 0)==0,'Existing recording active'
mem=int(next(x.split()[1] for x in open('/proc/meminfo') if x.startswith('MemAvailable:')))
assert mem>=2800000,'Host RAM headroom insufficient to pilot five slots'
assert Path('/opt/beonmeet/data/beonmeet.db').exists(),'Existing database missing'
print('FIVE_SLOT_DEPLOY_PRECHECK_PASS')
PY
for name in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$name")" = healthy ] || {
        echo CAMCAM_NOT_HEALTHY;exit 1;
    }
done
BACKUP="/opt/beonmeet/.five-slot-pilot-backup-$(date -u +%Y%m%dT%H%M%S)"
mkdir -m 700 "$BACKUP"
cp -p .env "$BACKUP/original.env"
docker inspect beonmeet-chrome-single > "$BACKUP/original-chrome-inspect.json"
docker inspect beonmeet-worker-single > "$BACKUP/original-worker-inspect.json"
docker cp beonmeet-worker-single:/usr/src/app/dist/bots/GoogleMeetBot.js "$BACKUP/GoogleMeetBot.original.js"
SOURCE_COMMIT=c585793c6b369ab72af7856ac038e22c6bdc5072
git fetch --quiet origin refs/heads/feat/five-concurrent-recorder-capacity-20261119
git show "$SOURCE_COMMIT:patches/patch_low_resource_compiled_recorder.py" > "$BACKUP/patcher.py"
python3 "$BACKUP/patcher.py" "$BACKUP/GoogleMeetBot.original.js" "$BACKUP/GoogleMeetBot.overlay.js"
docker run --rm --network none --memory=300m --cpus=.3 --entrypoint node -v "$BACKUP/GoogleMeetBot.overlay.js:/tmp/recorder.js:ro" beonmeet-worker-audiofix:latest --check /tmp/recorder.js
export BACKUP
python3 - <<'PY'
import json,os
from pathlib import Path
back=Path(os.environ['BACKUP'])
info=json.loads((back/'original-worker-inspect.json').read_text())[0]
env=info['Config'].get('Env') or []
with (back/'worker-five.env').open('w') as fp:
    for pair in env:
        if pair.startswith('MAX_CONCURRENT_MEETINGS='):continue
        if '\n' in pair or '\r' in pair:raise SystemExit('Unsupported multiline Docker env')
        fp.write(pair+'\n')
    fp.write('MAX_CONCURRENT_MEETINGS=5\n')
(back/'worker-five.env').chmod(0o600)
old=(back/'original.env').read_text()
desired={
    'FREE_MEETING_BOT_URL':'http://127.0.0.1:9126',
    'PREMIUM_MEETING_BOT_URL':'http://127.0.0.1:9126',
    'FREE_WORKER_URLS':'http://127.0.0.1:9126',
    'PREMIUM_WORKER_URLS':'http://127.0.0.1:9126',
    'FREE_MEETING_SLOTS':'5',
    'PREMIUM_MEETING_SLOTS':'0',
    'AUTOSCALE_ENABLED':'false',
}
output=[]
for line in old.splitlines():
    k=line.split('=',1)[0].strip() if '=' in line else ''
    if k in desired and not line.lstrip().startswith('#'):
        output.append(k+'='+desired.pop(k))
    else:output.append(line)
output += [k+'='+v for k,v in desired.items()]
p=back/'five-controller.env'
p.write_text('\n'.join(output)+'\n')
p.chmod(0o600)
PY
# A failed canary or controller restart MUST leave the existing 1-slot path up.
CHROME_TUNED=0
CONTROLLER_CHANGED=0
SUCCESS=0
rollback() {
    if [ "$SUCCESS" = 0 ];then
        echo FIVE_SLOT_ROLLBACK_START
        if [ "$CONTROLLER_CHANGED" = 1 ];then
            install -m 600 "$BACKUP/original.env" /opt/beonmeet/.env
            systemctl restart beonmeet-controller || true
        fi
        docker rm -f "$TARGET" >/dev/null 2>&1 || true
        if [ "$CHROME_TUNED" = 1 ];then
            docker update --memory=880m --memory-swap=1200m --cpus=.7 beonmeet-chrome-single >/dev/null 2>&1 || true
        fi
        echo FIVE_SLOT_ROLLBACK_DONE
    fi
}
trap rollback EXIT
# Original Chrome stays running with the signed-in Google profile.
# CPU/memory cgroup changes are live and do not restart Chrome/CamCam.
docker update --memory=2350m --memory-swap=2600m --cpus=1.45 beonmeet-chrome-single >/dev/null
CHROME_TUNED=1
docker run -d \
    --name "$TARGET" --network beonmeet-single \
    --memory=1150m --memory-swap=1350m --cpus=.8 --pids-limit=350 --shm-size=256m \
    --restart=unless-stopped -p 127.0.0.1:9126:3000 \
    --env-file "$BACKUP/worker-five.env" \
    -v /dev/shm/beonmeet:/recordings \
    -v "$BACKUP/GoogleMeetBot.overlay.js:/usr/src/app/dist/bots/GoogleMeetBot.js:ro" \
    beonmeet-worker-audiofix:latest >/dev/null
READY=0
for i in $(seq 1 20);do
    if curl -fsS --max-time 3 http://127.0.0.1:9126/health >/dev/null 2>&1;then READY=1;break;fi
    sleep 1
done
[ "$READY" = 1 ] || { echo FIVE_WORKER_HEALTH_FAILED;exit 1; }
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:9126/capacity',timeout=8) as r:d=json.load(r)
v=d.get('data') or d
assert int(v.get('availableSlots') or 0)==5, 'New worker not configured for 5 slots'
assert int(v.get('runningJobs') or 0)==0
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:c=json.load(r)
assert int(c.get('active_delivery_jobs') or 0)==0
assert int(c.get('pending_delivery_jobs') or 0)==0
with urllib.request.urlopen('http://127.0.0.1:9124/capacity',timeout=8) as r:e=json.load(r)
assert int((e.get('data') or e).get('runningJobs') or 0)==0
print('FIVE_WORKER_CANARY_HEALTH_PASS')
PY
CONTROLLER_CHANGED=1
install -m 600 "$BACKUP/five-controller.env" .env
systemctl restart beonmeet-controller
LIVE=0
for i in $(seq 1 24);do
    if curl -fsS --max-time 3 http://127.0.0.1:8109/health >/dev/null 2>&1;then LIVE=1;break;fi
    sleep 2
done
[ "$LIVE" = 1 ] || { echo CONTROLLER_RESTART_FAILED;exit 1; }
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:d=json.load(r)
assert d.get('ok')
assert int(d.get('max_concurrent_meetings') or 0)==5
assert int(d.get('local_free_meeting_slots') or 0)==5
assert not d.get('autoscaler_enabled')
with urllib.request.urlopen('http://127.0.0.1:9126/capacity',timeout=8) as r:c=json.load(r)
assert int((c.get('data') or c).get('availableSlots') or 0)==5
print('FIVE_SLOT_CONFIGURED_AND_HEALTHY')
PY
curl -fsS --max-time 12 https://beonmeet.smarbiz.sbs/health >/dev/null
systemctl is-active --quiet rednotedownloader
nginx -t >/dev/null 2>&1
for name in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$name")" = healthy ] || {
        echo CAMCAM_POST_DEPLOY_FAILED;exit 1;
    }
done
touch /opt/beonmeet/.five-slot-pilot-active
SUCCESS=1
echo FIVE_SLOT_PILOT_CONFIGURED
echo "BACKUP_DIR=$BACKUP"
echo "CAUTION: Not yet five real Google Meet recordings. Validate before advertising five guaranteed concurrent sessions."
