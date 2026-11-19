#!/usr/bin/env bash
# Single-host rollout from BeOnMeet 30-day subscriptions to prepaid recording credits.
# Requires known source baseline and idle controllers; NEVER touches other services.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST; exit 1 ;; esac
[ "$(id -u)" = 0 ] || { echo ROOT_REQUIRED; exit 1; }
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 60 9
cd /opt/beonmeet
[ -f .env ] && [ -s data/beonmeet.db ] || { echo MISSING_LIVE_DB_OR_ENV;exit 1; }
[ ! -e app/credit_wallet.py ] || { echo WALLET_ALREADY_INSTALLED_REVIEW_FIRST;exit 1; }
for service in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$service")" = healthy ] || { echo CAMCAM_PRECHECK_FAILED;exit 1; }
done
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:data=json.load(r)
assert data.get('ok') and int(data.get('max_concurrent_meetings') or 0)==5
for key in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(data.get(key) or 0)==0, key+' not idle'
for port in (9124,9126):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r:d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0,'active recorder'
print('WALLET_RELEASE_IDLE_PRECHECK_PASS')
PY
SOURCE=3ae6bb2892840130b09e32909e29696e5c15b799
PREVIOUS=b3220a0dd7c1f4ca72321f70544b38c22a0b099b
git fetch --quiet origin refs/heads/feat/prepaid-recording-hour-wallet-20261119
git merge-base --is-ancestor "$SOURCE" FETCH_HEAD || { echo REVIEWED_SOURCE_NOT_FETCHED;exit 1; }
for file in main.py admin_panel.py i18n.py billing_policy.py;do
  cmp -s "app/$file" <(git show "$PREVIOUS:app/$file") || { echo LIVE_SOURCE_CHANGED_$file;exit 1; }
done
BACKUP="/opt/beonmeet/.prepaid-wallet-backup-$(date -u +%Y%m%dT%H%M%S)"
STAGE=$(mktemp -d /opt/beonmeet/.stage-prepaid-wallet.XXXXXXXX)
mkdir -m 700 "$BACKUP"
export STAGE BACKUP
for file in main.py admin_panel.py i18n.py billing_policy.py credit_wallet.py;do
    git show "$SOURCE:app/$file" > "$STAGE/$file"
    chmod 644 "$STAGE/$file"
done
.venv/bin/python -m py_compile "$STAGE"/{main,admin_panel,i18n,billing_policy,credit_wallet}.py
tar -czf "$BACKUP/source-env.tar.gz" app/main.py app/admin_panel.py app/i18n.py app/billing_policy.py .env
chmod 600 "$BACKUP/source-env.tar.gz"
if [ -s data/state.json ];then cp -p data/state.json "$BACKUP/state-before.json";fi
python3 - <<'PY'
import os,sqlite3
from pathlib import Path
src=Path('/opt/beonmeet/data/beonmeet.db')
dst=sqlite3.connect(os.environ['BACKUP']+'/db-before.sqlite')
ori=sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True)
ori.backup(dst)
dst.close();ori.close()
os.chmod(os.environ['BACKUP']+'/db-before.sqlite',0o600)
print('WALLET_BACKUP_DB_SOURCE_STATE_COMPLETE')
PY
# Protect against actual customer sessions starting while staging.
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:data=json.load(r)
for key in ('free_queue','premium_queue','active_delivery_jobs','pending_delivery_jobs'):
    assert int(data.get(key) or 0)==0,key+' became active'
for port in (9124,9126):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/capacity',timeout=8) as r:d=json.load(r)
    assert int((d.get('data') or d).get('runningJobs') or 0)==0,'recording started while staging'
PY
CHANGED=0
SUCCESS=0
rollback() {
    if [ "$CHANGED" = 1 ] && [ "$SUCCESS" = 0 ];then
       echo PREPAID_WALLET_ROLLBACK_CODE_BEGIN
       tar -xzf "$BACKUP/source-env.tar.gz" -C /opt/beonmeet || true
       rm -f app/credit_wallet.py
       # Never restore a stale DB automatically: protect any transactions
       # accepted after the controller restarted. DB backup is retained.
       systemctl restart beonmeet-controller || true
       echo PREPAID_WALLET_ROLLBACK_CODE_COMPLETE
    fi
}
trap rollback EXIT
CHANGED=1
for file in main.py admin_panel.py i18n.py billing_policy.py credit_wallet.py;do
    install -m 644 "$STAGE/$file" "app/$file"
done
systemctl restart beonmeet-controller
HEALTHY=0
for i in $(seq 1 30);do
    if curl -fsS --max-time 3 http://127.0.0.1:8109/health >/dev/null 2>&1;then HEALTHY=1;break;fi
    sleep 2
done
[ "$HEALTHY" = 1 ] || { echo WALLET_CONTROLLER_STARTUP_FAILED;exit 1; }
.venv/bin/python - <<'PY'
from pathlib import Path
import sqlite3,json,urllib.request,sys
p=Path('/opt/beonmeet/data/beonmeet.db')
db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert 'credit_entries' in tables,'credit ledger not created'
rows=db.execute("SELECT COUNT(*), COALESCE(SUM(seconds_delta),0) FROM credit_entries").fetchone()
print('WALLET_LIVE_LEDGER_TOTAL_RECORDS=',rows[0],'NET_SECONDS=',rows[1])
sys.path.insert(0,'/opt/beonmeet/app')
from i18n import MESSAGES,PROFILE_TEXT,menu
for lang in ('fa','en','de'):
    for key in ('wallet_balance','wallet_payment_confirmed','wallet_empty','premium_offer'):
        assert MESSAGES[lang][key]
    assert 'credits' in PROFILE_TEXT[lang]['commands']
    assert '/credits' == __import__('i18n').BUTTON_ACTIONS[menu(lang)['premium']]
from billing_policy import PUBLIC_PLAN_CODES,PUBLIC_PLANS
assert [PUBLIC_PLANS[x]['price'] for x in PUBLIC_PLAN_CODES]==[298000,498000,998000]
with urllib.request.urlopen('http://127.0.0.1:8109/health',timeout=8) as r:data=json.load(r)
assert data.get('ok') and int(data.get('max_concurrent_meetings') or 0)==5
for page,phrase in (('/fa','ساعت‌ها تاریخ انقضا ندارند'),('/','Hours never expire')):
    with urllib.request.urlopen('http://127.0.0.1:8109'+page,timeout=8) as r:body=r.read().decode()
    assert phrase in body,(page,phrase)
print('WALLET_NEW_SALE_AND_DISPLAY_CHECK_PASS')
PY
curl -fsS --max-time 12 https://beonmeet.smarbiz.sbs/fa >/dev/null
nginx -t >/dev/null 2>&1
systemctl is-active --quiet rednotedownloader
for service in camcam-shared-api-1 camcam-shared-pet-1 camcam-shared-archive-1 camcam-shared-petarchive-1;do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$service")" = healthy ] || { echo CAMCAM_POSTCHECK_FAILED;exit 1; }
done
SUCCESS=1
echo PREPAID_WALLET_LIVE_DEPLOY_SUCCESS
echo "BACKUP_DIR=$BACKUP"
# Telegram command cache is updated on controller startup; verify separately,
# but do not roll back the working financial ledger because of API rate limits.
.venv/bin/python - <<'PY'
import json,urllib.request,time
from pathlib import Path
env={}
for line in Path('/opt/beonmeet/.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
token=env.get('TELEGRAM_BOT_TOKEN')
base=env.get('TELEGRAM_API_BASE','https://api.telegram.org').rstrip('/')
if token:
    for lang in ('fa','en','de'):
        good=False
        for attempt in range(6):
            try:
                payload=json.dumps({'scope':{'type':'all_private_chats'},'language_code':lang}).encode()
                request=urllib.request.Request(base+'/bot'+token+'/getMyCommands',data=payload,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=8) as r:data=json.load(r)
                cmds=[x.get('command') for x in (data.get('result') or [])]
                if data.get('ok') and 'credits' in cmds and 'plans' not in cmds and 'auto' not in cmds:
                    good=True;break
            except Exception:pass
            time.sleep(2)
        print('TELEGRAM_CREDIT_COMMAND_'+lang+'='+str(good))
PY
rm -rf "$STAGE"
