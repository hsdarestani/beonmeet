#!/usr/bin/env bash
# Roll back the five-slot trial to the unchanged original worker (port 9124).
# By default refuses to interrupt active recordings, queues or deliveries.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST;exit 1;; esac
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 45 9
cd /opt/beonmeet
test -e .five-slot-pilot-active || { echo FIVE_SLOT_NOT_ENABLED; exit 0; }
BACKUP="${1:-}"
if [ -z "$BACKUP" ];then
    BACKUP=$(find /opt/beonmeet -maxdepth 1 -type d -name '.five-slot-pilot-backup-*' | sort | tail -1)
fi
[ -n "$BACKUP" ] && [ -s "$BACKUP/original.env" ] || { echo BACKUP_MISSING;exit 1; }
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:d=json.load(r)
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(d.get(k) or 0)==0,k+' not idle'
for url in ('http://127.0.0.1:9126/capacity','http://127.0.0.1:9124/capacity'):
    with urllib.request.urlopen(url,timeout=8) as r:c=json.load(r)
    assert int((c.get('data') or c).get('runningJobs') or 0)==0,url+' has active recording'
print('FIVE_SLOT_ROLLBACK_IDLE_CHECK_PASS')
PY
cp -p .env "$BACKUP/pre-rollback-five.env"
install -m 600 "$BACKUP/original.env" .env
systemctl restart beonmeet-controller
READY=0
for i in $(seq 1 25);do
    if curl -fsS --max-time 3 http://127.0.0.1:8109/health >/dev/null 2>&1;then READY=1;break;fi
    sleep 2
done
if [ "$READY" != 1 ] || ! python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:d=json.load(r)
assert int(d.get('max_concurrent_meetings') or 0)==1
PY
then
    echo ORIGINAL_WORKER_ROLLBACK_FAILED_RESTORING_FIVE
    install -m 600 "$BACKUP/pre-rollback-five.env" .env
    systemctl restart beonmeet-controller || true
    exit 1
fi
docker rm -f beonmeet-worker-five >/dev/null 2>&1 || true
docker update --memory=880m --memory-swap=1200m --cpus=.7 beonmeet-chrome-single >/dev/null 2>&1 || true
rm -f /opt/beonmeet/.five-slot-pilot-active
curl -fsS --max-time 8 https://beonmeet.smarbiz.sbs/health >/dev/null
echo ORIGINAL_SINGLE_SLOT_RESTORED
