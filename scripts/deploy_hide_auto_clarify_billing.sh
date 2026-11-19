#!/usr/bin/env bash
# One-time safe BeOnMeet bot copy + feature availability release on shared VPS.
# No restart of Chrome, CamCam, recording workers or payment gateway.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST; exit 1 ;; esac
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 50 9
cd /opt/beonmeet
[ -s .env ] || { echo BEONMEET_ENV_MISSING; exit 1; }
for s in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$s")" = healthy ] || { echo CAMCAM_NOT_HEALTHY_$s; exit 1; }
done
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:h=json.load(r)
assert h.get('ok') and int(h.get('max_concurrent_meetings') or 0)==5
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(h.get(k) or 0)==0,k+' is busy'
for port in (9126,9124):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r:d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0,'recording is active'
print('BOT_SAFE_IDLE_PRECHECK_PASS')
PY
# The previous controlled deploy intentionally left three files dirty relative
# to the original detached git HEAD. Require byte-for-byte equality with the
# *known deployed commit* rather than trusting an empty git status.
PREVIOUS_REVIEWED=1e6319bd41d848d75c1659074640aa0b02d8f906
for name in main.py admin_panel.py i18n.py;do
  cmp -s <(git show "$PREVIOUS_REVIEWED:app/$name") "app/$name" || {
    echo UNEXPECTED_LOCAL_APP_CHANGE_$name
    exit 1
  }
done
SOURCE=18099aca6d727baddd26700828da74aeaf932fe4
git fetch --quiet origin refs/heads/fix/hide-auto-and-clarify-subscription-20261119
git merge-base --is-ancestor "$SOURCE" FETCH_HEAD || { echo REVIEWED_COMMIT_NOT_FOUND; exit 1; }
STAGE=$(mktemp -d /opt/beonmeet/.stage-hidemeet.XXXXXXXX)
BACKUP="/opt/beonmeet/.hide-auto-billing-backup-$(date -u +%Y%m%dT%H%M%S)"
mkdir -m 700 "$BACKUP"
export STAGE BACKUP
for name in main.py admin_panel.py i18n.py;do
  git show "$SOURCE:app/$name" > "$STAGE/$name"
  chmod 644 "$STAGE/$name"
done
.venv/bin/python -m py_compile "$STAGE/main.py" "$STAGE/admin_panel.py" "$STAGE/i18n.py"
tar -czf "$BACKUP/app-env-before.tar.gz" app/main.py app/admin_panel.py app/i18n.py .env
chmod 600 "$BACKUP/app-env-before.tar.gz"
if [ -e data/state.json ];then cp -p data/state.json "$BACKUP/state-before.json"; fi
python3 - <<'PY'
import sqlite3,os
db=sqlite3.connect('file:/opt/beonmeet/data/beonmeet.db?mode=ro',uri=True)
backup=sqlite3.connect(os.environ['BACKUP']+'/database-before.sqlite')
db.backup(backup)
backup.close();db.close()
print('BOT_SAFE_SQLITE_AND_STATE_BACKUP_COMPLETE')
PY
python3 - <<'PY'
import os
from pathlib import Path
source=Path('/opt/beonmeet/.env')
lines=source.read_text().splitlines()
new=[];found=False
for line in lines:
    if not line.lstrip().startswith('#') and line.split('=',1)[0].strip()=='AUTO_ALL_MEETINGS_ENABLED':
        if not found:new.append('AUTO_ALL_MEETINGS_ENABLED=false');found=True
    else:new.append(line)
if not found:new.append('AUTO_ALL_MEETINGS_ENABLED=false')
out=Path(os.environ['STAGE'])/'desired.env'
out.write_text('\n'.join(new)+'\n')
out.chmod(0o600)
print('BOT_AUTO_DISABLED_FLAG_STAGED')
PY
# Avoid modifying any running recording/delivery as the files are staged.
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:h=json.load(r)
for k in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(h.get(k) or 0)==0,k+' was queued while staging'
for port in (9126,9124):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r:d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0,'meeting started during staging'
PY
INSTALLED=0
SUCCESS=0
rollback() {
  if [ "$INSTALLED" = 1 ] && [ "$SUCCESS" = 0 ];then
    echo BOT_LAUNCH_ROLLBACK_START
    tar -xzf "$BACKUP/app-env-before.tar.gz" -C /opt/beonmeet || true
    if [ -f "$BACKUP/state-before.json" ];then cp -p "$BACKUP/state-before.json" /opt/beonmeet/data/state.json;fi
    systemctl restart beonmeet-controller || true
    echo BOT_LAUNCH_ROLLBACK_COMPLETE
  fi
}
trap rollback EXIT
INSTALLED=1
for name in main.py admin_panel.py i18n.py;do
  install -m 644 "$STAGE/$name" "app/$name"
done
install -m 600 "$STAGE/desired.env" .env
systemctl restart beonmeet-controller
READY=0
for i in $(seq 1 25);do
  if curl -fsS --max-time 3 http://127.0.0.1:8109/health >/dev/null 2>&1;then READY=1;break;fi
  sleep 2
done
[ "$READY" = 1 ] || { echo BOT_NOT_HEALTHY_AFTER_CHANGE; exit 1; }
.venv/bin/python - <<'PY'
import json,urllib.request,os,sys
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:d=json.load(r)
assert d.get('ok') and int(d.get('max_concurrent_meetings') or 0)==5
sys.path.insert(0,'/opt/beonmeet/app')
from i18n import MESSAGES,PROFILE_TEXT
for lang in ('fa','en','de'):
    for k in ('premium_offer','payment_confirmed','payment_scheduled','renewal_scheduled','manual_mode_notice','auto_unavailable'):
        assert MESSAGES[lang].get(k),lang+':'+k
    assert 'auto' not in PROFILE_TEXT[lang]['commands']
print('BOT_FIVE_SLOTS_AND_THREE_LANGUAGE_BILLING_COPY_VERIFIED')
with urllib.request.urlopen('http://127.0.0.1:8109/fa',timeout=8) as r:html=r.read().decode()
assert 'خرید دوباره سهمیه همان دوره را افزایش نمی‌دهد' in html
assert 'همه جلسات' not in html
with urllib.request.urlopen('http://127.0.0.1:8109/',timeout=8) as r:english=r.read().decode()
assert 'another plan purchase starts only after' in english
assert 'automatically join all meetings' not in english
print('BOT_LANDING_PAGE_COPY_AND_HIDDEN_AUTOMEETINGS_VERIFIED')
PY
curl -fsS --max-time 12 https://beonmeet.smarbiz.sbs/fa >/dev/null
systemctl is-active --quiet rednotedownloader
nginx -t >/dev/null 2>&1
for s in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$s")" = healthy ] || { echo CAMCAM_NOT_HEALTHY_AFTER_$s;exit 1; }
done
# Commit only after all service-related checks pass, preserving the current
# safety change even if Telegram API is delayed by rate-limiting.
SUCCESS=1
echo BOT_AUTO_MODE_HIDDEN_AND_SUBSCRIPTION_COPY_LIVE
echo "BACKUP_DIR=$BACKUP"
# The Telegram profile is updated asynchronously by the controller on startup.
.venv/bin/python - <<'PY'
import os,json,urllib.request,time
from pathlib import Path
p=Path('/opt/beonmeet/.env')
env={}
for line in p.read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
token=env.get('TELEGRAM_BOT_TOKEN')
base=env.get('TELEGRAM_API_BASE','https://api.telegram.org').rstrip('/')
assert token
for lang in ('fa','en','de'):
    ok=False
    for attempt in range(6):
        try:
            payload=json.dumps({'scope':{'type':'all_private_chats'},'language_code':lang}).encode('utf-8')
            url=base+'/bot'+token+'/getMyCommands'
            req=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=8) as r:result=json.load(r)
            commands=[item.get('command') for item in (result.get('result') or [])]
            if result.get('ok') and commands and 'auto' not in commands:
                ok=True;break
        except Exception:pass
        time.sleep(2)
    print('TELEGRAM_AUTO_HIDDEN_'+lang+'='+str(ok))
PY
rm -rf "$STAGE"
