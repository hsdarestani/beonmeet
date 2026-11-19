#!/usr/bin/env bash
# One-time hotfix for HamoonCloud's BeOnMeet payment plan compatibility.
# Only modifies external-payments.js within HamoonCloud on the existing VPS.
# Never modifies transaction history, merchant credentials, or other app routes.
set -euo pipefail
umask 077
case " $(hostname -I) " in *" 143.20.60.195 "*) : ;; *) echo WRONG_HOST;exit 1;; esac
[ "$(id -u)" -eq 0 ] || { echo ROOT_REQUIRED;exit 1; }
exec 9>/var/lock/pars-vds-bot-deploy.lock
flock -w 35 9
SOURCE=/home/hamoondeploy/hamoon-source/external-payments.js
test -f "$SOURCE"
systemctl is-active --quiet hamoon-dashboard
node --check "$SOURCE"
WORK=$(mktemp -d /home/hamoondeploy/.payment-gateway-hotfix.XXXXXXXX)
chmod 700 "$WORK"
cp -p "$SOURCE" "$WORK/original-external-payments.js"
CHANGED=0
SUCCESS=0
restore() {
  if [ "$CHANGED" = 1 ] && [ "$SUCCESS" = 0 ]; then
    echo HAMOONCLOUD_HOTFIX_ROLLBACK_BEGIN
    cp -p "$WORK/original-external-payments.js" "$SOURCE"
    systemctl restart hamoon-dashboard || true
    echo HAMOONCLOUD_HOTFIX_ROLLBACK_COMPLETE
  fi
}
trap restore EXIT
git -C /opt/beonmeet fetch --quiet origin refs/heads/fix/payment-intent-gateway-20261119
git -C /opt/beonmeet show 2658facfb884f77dee8fd6177bacaf101b4e79a6:patches/fix_hamooncloud_beonmeet_plans.py > "$WORK/patcher.py"
python3 "$WORK/patcher.py" "$SOURCE" "$WORK/patched-external-payments.js"
node --check "$WORK/patched-external-payments.js"
if cmp -s "$SOURCE" "$WORK/patched-external-payments.js"; then
  echo HAMOONCLOUD_PLAN_ALLOWLIST_ALREADY_APPLIED
  SUCCESS=1
  exit 0
fi
python3 - "$SOURCE" "$WORK/patched-external-payments.js" <<'PY'
import sys,importlib.util
from pathlib import Path
original=Path(sys.argv[1]).read_text()
patched=Path(sys.argv[2]).read_text()
spec=importlib.util.spec_from_file_location('payment_patch','/dev/null')
old="!['monthly','quarterly','halfyear'].includes(plan)"
new="!['monthly','quarterly','halfyear','basic','pro','business'].includes(plan)"
assert original.count(old)>=1
assert patched.count(new)==1
assert patched.replace(new,old,1)==original, 'Unexpected additional changes'
print('GATEWAY_PATCH_SCOPE_CONFIRMED')
PY
python3 - "$SOURCE" "$WORK/patched-external-payments.js" <<'PY'
import os,sys,stat,tempfile,shutil
from pathlib import Path
src=Path(sys.argv[1]);patch=Path(sys.argv[2])
current=src.stat()
fd,p=tempfile.mkstemp(prefix='.beonmeet-payment-hotfix-',dir=src.parent)
try:
    with os.fdopen(fd,'wb') as f: f.write(patch.read_bytes())
    os.chmod(p,stat.S_IMODE(current.st_mode))
    os.chown(p,current.st_uid,current.st_gid)
    os.replace(p,src)
except BaseException:
    try:os.unlink(p)
    except OSError:pass
    raise
print('HAMOON_GATEWAY_FILE_PATCHED_ATOMICALLY')
PY
CHANGED=1
systemctl restart hamoon-dashboard
READY=0
for i in $(seq 1 25);do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 'http://127.0.0.1:8108/payments/beonmeet/start' || true)
  if [ "$code" = 400 ];then READY=1;break;fi
  sleep 1
done
[ "$READY" = 1 ] || { echo 'Gateway did not recover from restart';exit 1; }
systemctl is-active --quiet hamoon-dashboard
# Confirm prior CamCam route stayed valid; missing-intent must give expected 400.
CAMCAM=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 6 'http://127.0.0.1:8108/payments/camcam/start')
[ "$CAMCAM" = 400 ] || { echo CAMCAM_GATEWAY_REGRESSION;exit 1; }
python3 - <<'PY'
import datetime,sqlite3,urllib.request,urllib.error,urllib.parse
now=datetime.datetime.now(datetime.timezone.utc)
db=sqlite3.connect('file:/opt/beonmeet/data/beonmeet.db?mode=ro',uri=True);db.row_factory=sqlite3.Row
rows=db.execute("""SELECT intent,plan_code,expires_at FROM payment_intents
                   WHERE status='pending' ORDER BY created_at DESC LIMIT 30""").fetchall()
tested=0
for row in rows:
    exp=datetime.datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))
    if exp<=now or row['plan_code'] not in ('basic','pro','business'):continue
    token=urllib.parse.quote(row['intent'],safe='')
    url='http://127.0.0.1:8108/payments/beonmeet/start?intent='+token
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,request,fp,code,msg,headers,newurl):return None
    req=urllib.request.Request(url,headers={'User-Agent':'BeOnMeet-payment-fix-validation/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response: status=response.status
    except urllib.error.HTTPError as e: status=e.code
    print('BEONMEET_VALID_GATEWAY_INTENT_PLAN=',row['plan_code'],'HTTP=',status)
    if status==409:
        raise SystemExit('EXISTING_VALID_INTENT_STILL_REJECTED')
    if status in (301,302,303,307,308):
        print('GATEWAY_PAYMENT_REDIRECT_READY')
    elif status==502:
        print('GATEWAY_PLAN_FIXED_BUT_UPSTREAM_PAYMENT_PROVIDER_ERROR')
    else:
        print('GATEWAY_UNEXPECTED_RESPONSE=',status)
    tested+=1
    break
if not tested:
    print('NO_FRESH_INTENT_AVAILABLE_FOR_LIVE_GATEWAY_CHECK')
PY
SUCCESS=1
echo HAMOONCLOUD_BEONMEET_PLAN_FIX_DEPLOYED
echo "BACKUP=$WORK"
echo 'NO_FUNDS_CHARGED_AND_OTHER_APPLICATION_HANDLERS_UNCHANGED'
