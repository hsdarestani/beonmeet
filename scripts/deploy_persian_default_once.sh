#!/usr/bin/env bash
# Safe one-time release: Persian-first interface only. Does not edit database, state, workers or CamCam.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST; exit 1;; esac
test "$(id -u)" = 0 || { echo ROOT_REQUIRED; exit 1; }
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 60 9
cd /opt/beonmeet
test -s .env && test -s data/beonmeet.db
systemctl is-active --quiet beonmeet-controller
for svc in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1; do
  test "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" = healthy || { echo CAMCAM_UNHEALTHY; exit 1; }
done
.venv/bin/python - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r: h=json.load(r)
assert h.get('ok') and int(h.get('max_concurrent_meetings') or 0)==5
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(h.get(k) or 0)==0,k
for port in (9124,9126):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r: d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0
print('PERSIAN_DEFAULT_IDLE_PRECHECK_PASS')
PY
BASE=b460966967a5213f7bc82eff17b8b20804cab53a
SOURCE=b22c372e9741c38edc27f228cadf298d6147d21a
git fetch --quiet origin main
git merge-base --is-ancestor "$SOURCE" FETCH_HEAD || { echo REVIEWED_SOURCE_NOT_MERGED; exit 1; }
for f in main.py i18n.py; do
  cmp -s "app/$f" <(git show "$BASE:app/$f") || { echo LIVE_SOURCE_CHANGED_"$f"; exit 1; }
done
BACKUP="/opt/beonmeet/.farsi-default-backup-$(date -u +%Y%m%dT%H%M%SZ)"
STAGE=$(mktemp -d /opt/beonmeet/.stage-farsi.XXXXXXXX)
mkdir -m 700 "$BACKUP"
export BACKUP
for f in main.py i18n.py; do git show "$SOURCE:app/$f" > "$STAGE/$f"; done
.venv/bin/python -m py_compile "$STAGE/main.py" "$STAGE/i18n.py"
tar -czf "$BACKUP/code-env.tar.gz" app/main.py app/i18n.py .env
chmod 600 "$BACKUP/code-env.tar.gz"
if test -s data/state.json; then cp -p data/state.json "$BACKUP/state-before.json"; fi
.venv/bin/python - <<'PY'
import sys,json,hashlib,os
from pathlib import Path
sys.path.insert(0,'/opt/beonmeet/app')
from state_store import DurableStateStore
s,origin=DurableStateStore(Path('/opt/beonmeet/data/state.json')).load()
assert isinstance(s,dict)
langs=s.get('user_languages') or {}
assert isinstance(langs,dict)
Path(os.environ['BACKUP'],'languages.json').write_text(json.dumps(langs,ensure_ascii=False))
print('SAVED_LANGUAGES_BACKED_UP_FROM_'+origin.upper())
PY
# Recheck idle immediately before restart
.venv/bin/python - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r: h=json.load(r)
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(h.get(k) or 0)==0
for port in (9124,9126):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r: d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0
PY
CHANGED=0; SUCCESS=0
cleanup() {
  if test "$CHANGED" = 1 && test "$SUCCESS" = 0; then
    echo RESTORE_OLD_CONTROLLER_SOURCE
    tar -xzf "$BACKUP/code-env.tar.gz" -C /opt/beonmeet || true
    systemctl restart beonmeet-controller || true
  fi
  rm -rf "$STAGE"
}
trap cleanup EXIT
CHANGED=1
for f in main.py i18n.py; do install -m 644 "$STAGE/$f" "app/$f"; done
systemctl restart beonmeet-controller
OK=0
for i in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8109/health >/dev/null 2>&1; then OK=1; break; fi
  sleep 2
done
test "$OK" = 1 || { echo CONTROLLER_NOT_HEALTHY; exit 1; }
.venv/bin/python - <<'PY'
import json,os,sys
from pathlib import Path
sys.path.insert(0,'/opt/beonmeet/app')
import i18n
assert i18n.DEFAULT_LANGUAGE=='fa'
assert i18n.normalize_language(None)=='fa'
assert i18n.normalize_language('en')=='en'
assert i18n.normalize_language('de')=='de'
assert i18n.profile(None)['commands']['start']=='راهنمای استفاده'
source=Path('/opt/beonmeet/app/main.py').read_text()
assert 'user_languages[str(chat_id)] = DEFAULT_LANGUAGE' in source
from state_store import DurableStateStore
state,_=DurableStateStore(Path('/opt/beonmeet/data/state.json')).load()
saved=json.loads(Path(os.environ['BACKUP'],'languages.json').read_text())
assert isinstance(state,dict) and (state.get('user_languages') or {})==saved
print('PERSIAN_DEFAULT_RUNTIME_AND_SAVED_LANGUAGES_PASS')
PY
curl -fsS --max-time 12 https://beonmeet.smarbiz.sbs/health >/dev/null
nginx -t >/dev/null
systemctl is-active --quiet rednotedownloader
for svc in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1; do
  test "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" = healthy || { echo CAMCAM_POSTCHECK_FAILED; exit 1; }
done
SUCCESS=1
echo BEONMEET_PERSIAN_DEFAULT_DEPLOY_SUCCESS
echo "BACKUP_DIR=$BACKUP"
