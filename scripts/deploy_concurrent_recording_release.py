#!/usr/bin/env python3
"""Pinned production cutover on the existing VPS, with exact test-only drain.

Caller holds the existing shared deployment lock. Never restart a lane with
any unrecognized active work. Never modify the database, Redis, Google profile
or unrelated containers. The two November 25 failed test sessions are the
only authorized exceptions to the idle check; their files are not deleted.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.request

ROOT = pathlib.Path('/opt/beonmeet')
BASE = '20c5de26360ab083082fe41767a13ec3e4626501'
CONTROLLER = 'beonmeet-controller'
PORTS = (9124, 9126, 9132, 9133, 9134, 9135)
WORKERS = ['beonmeet-worker-five'] + [f'beonmeet-isolated-worker-{i}' for i in range(2, 6)]
BOT_JS = '/usr/src/app/dist/bots/GoogleMeetBot.js'
UPLOADER_JS = '/usr/src/app/dist/middleware/disk-uploader.js'
FILES = ('app/main.py', 'app/admin_panel.py', 'app/i18n.py', 'app/state_store.py', 'app/recording_handoff.py')
TESTS = {'obi-fudd-kmu': ('premium-1', 9126, 'beonmeet-chrome-single'),
         'dva-wbnh-qik': ('premium-3', 9133, 'beonmeet-isolated-chrome-3')}
ACTIVE = {'joining', 'reserved', 'waiting_for_admission', 'capturing', 'recording', 'delivering', 'remote_claimed'}


def run(*args, timeout=45, input=None):
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, timeout=timeout, input=input).stdout


def json_url(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path}', timeout=6) as response:
        return json.load(response)


def capacities():
    result = {}
    for p in PORTS:
        payload = json_url(p, 'capacity')
        result[p] = int((payload.get('data') or payload)['runningJobs'])
    return result


def guard(health=True):
    if health:
        h = json_url(8109, 'health')
        assert h.get('ok'), 'CONTROLLER_UNHEALTHY'
        assert not any(int(h.get(k) or 0) for k in ('free_queue', 'premium_queue', 'active_delivery_jobs', 'pending_delivery_jobs')), 'USER_QUEUE_OR_DELIVERY_BUSY'
    state = json.loads((ROOT / 'data/state.json').read_text())
    assert not state.get('join_queue') and not state.get('pending_deliveries'), 'DURABLE_QUEUE_BUSY'
    active = [v for v in state.get('launched_events', {}).values() if v.get('status') in ACTIVE]
    known_ports = set()
    for job in active:
        url = str(job.get('meet_url') or '').rstrip('/')
        code = url.rsplit('/', 1)[-1]
        assert code in TESTS and job.get('status') == 'recording', 'UNRECOGNIZED_ACTIVE_CUSTOMER'
        pool, port, _ = TESTS[code]
        assert job.get('pool') == pool and port not in known_ports, 'UNKNOWN_TEST_JOB_MAPPING'
        known_ports.add(port)
    current = capacities()
    assert all(count == 0 or (p in known_ports and count == 1) for p, count in current.items()), 'UNRECOGNIZED_WORKER_ACTIVITY'
    print('DRAIN_GUARD_PASS', 'known_test_jobs', len(known_ports), 'active_slots', sum(current.values()), flush=True)
    return known_ports


def camcam_guard():
    for n in ('camcam-shared-api-1','camcam-shared-pet-1','camcam-shared-archive-1','camcam-shared-petarchive-1'):
        assert run('docker', 'inspect', '-f', '{{.State.Health.Status}}', n).decode().strip() == 'healthy', 'UNRELATED_SERVICE_UNHEALTHY'


def stage_release(release, stage):
    for filename in FILES:
        live = ROOT / filename
        new = stage / filename
        new.parent.mkdir(parents=True, exist_ok=True)
        target = run('git', 'show', f'{release}:{filename}')
        if live.exists():
            base = stage / (live.name + '.base')
            patch = stage / (live.name + '.release')
            base.write_bytes(run('git', 'show', f'{BASE}:{filename}'))
            patch.write_bytes(target)
            merged = subprocess.run(['git', 'merge-file', '-p', str(live), str(base), str(patch)], capture_output=True, timeout=20)
            assert merged.returncode == 0, f'LIVE_SOURCE_MERGE_CONFLICT {filename}'
            new.write_bytes(merged.stdout)
        else:
            assert filename == 'app/recording_handoff.py', f'MISSING_LIVE_SOURCE {filename}'
            new.write_bytes(target)
        compile(new.read_text(), str(new), 'exec')
    mounts = []
    uploader_hashes = []
    for worker in WORKERS:
        info = json.loads(run('docker','inspect',worker))[0]
        mount = next(m for m in info['Mounts'] if m['Destination'] == BOT_JS)
        overlay = pathlib.Path(mount['Source']).resolve()
        assert overlay.is_relative_to(ROOT) and overlay.is_file(), 'UNKNOWN_BOT_OVERLAY'
        mounts.append(overlay)
        source = stage / (worker + '.uploader.js')
        run('docker','cp',worker + ':' + UPLOADER_JS,str(source))
        uploader_hashes.append(hashlib.sha256(source.read_bytes()).hexdigest())
    assert len(set(mounts)) == 1, 'BOT_OVERLAY_MOUNTS_DIFFER'
    print('DISTINCT_LIVE_UPLOADER_VERSIONS',len(set(uploader_hashes)),flush=True)
    transformations = [('patches/patch_recording_finalization.py', mounts[0], stage/'bot.fixed.js')]
    transformations += [('patches/patch_compiled_uploader_handoff.py', stage/(w+'.uploader.js'), stage/(w+'.uploader.fixed.js')) for w in WORKERS]
    for script, original, fixed in transformations:
        patcher = stage / pathlib.Path(script).name
        patcher.write_bytes(run('git','show',f'{release}:{script}'))
        try:
            run('python3',str(patcher),str(original),str(fixed))
        except subprocess.CalledProcessError as exc:
            print('COMPILED_PATCH_REJECTED',original.name,exc.stderr.decode(errors='replace').splitlines()[-1][:300],flush=True)
            raise
        run('docker','exec','-i',WORKERS[0],'node','--check',input=fixed.read_bytes())
        os.chmod(fixed,0o644)
        print('COMPILED_PATCH_VALIDATED',fixed.name,flush=True)
    print('STAGED_CONTROLLER_AND_COMPILED_WORKERS_VALIDATED',flush=True)
    return mounts[0]


def close_stale_test_tabs(known_ports):
    for code, (_, p, chrome) in TESTS.items():
        if p not in known_ports:
            continue
        targets = json.loads(run('docker','exec',chrome,'curl','-fsS','--max-time','4','http://127.0.0.1:9223/json/list'))
        for t in targets:
            if str(t.get('url','')).split('?',1)[0].rstrip('/') == 'https://meet.google.com/'+code and t.get('type') == 'page':
                target = str(t['id'])
                assert target.isalnum(), 'UNKNOWN_CDP_TARGET_FORMAT'
                run('docker','exec',chrome,'curl','-fsS','--max-time','5','http://127.0.0.1:9223/json/close/'+target)
                print('CLOSED_ONLY_OBSOLETE_TEST_TAB',code,flush=True)


def wait_workers():
    for _ in range(30):
        try:
            assert not any(capacities().values()), 'WORKER_NOT_IDLE'
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError('WORKER_CAPACITY_NOT_READY')


def wait_controller():
    for _ in range(30):
        try:
            h=json_url(8109,'health')
            if h.get('ok') and 'pending_transcription_jobs' in h and int(h.get('free_worker_endpoints') or 0)==5:
                return h
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('NEW_CONTROLLER_HEALTH_FAILED')


def main(release):
    assert ROOT.is_dir() and os.geteuid() == 0
    assert '143.20.60.195' in run('hostname','-I').decode().split(), 'WRONG_HOST'
    assert len(release)==40 and all(c in '0123456789abcdef' for c in release)
    run('git','merge-base','--is-ancestor',release,'FETCH_HEAD')
    camcam_guard()
    guard()
    with tempfile.TemporaryDirectory(prefix='.concurrent-release-', dir=ROOT) as temp:
        stage=pathlib.Path(temp)
        overlay=stage_release(release,stage)
        backup=pathlib.Path(tempfile.mkdtemp(prefix='.concurrent-backup-',dir=ROOT))
        for name in FILES:
            src=ROOT/name
            if src.exists():
                dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        shutil.copy2(overlay,backup/'bot.before.js')
        (backup/'overlay-path.txt').write_text(str(overlay))
        for w in WORKERS:
            shutil.copy2(stage/(w+'.uploader.js'),backup/(w+'.uploader.js'))
        print('ROLLBACK_BACKUP_READY',backup,flush=True)
        controller_stopped=False
        changed=False
        workers_stopped=False
        try:
            guard()
            run('systemctl','stop',CONTROLLER,timeout=60)
            controller_stopped=True
            known=guard(health=False)
            close_stale_test_tabs(known)
            try:
                run('docker','stop','--time','15',*WORKERS,timeout=120)
            except Exception:
                run('docker','start',*WORKERS,timeout=120)
                raise
            workers_stopped=True
            changed=True
            # The shared file is a bind-mounted inode; write it only after all
            # five recorder processes have stopped.
            overlay.write_bytes((stage/'bot.fixed.js').read_bytes())
            for w in WORKERS:
                run('docker','cp',str(stage/(w+'.uploader.fixed.js')),w+':'+UPLOADER_JS)
            for name in FILES:
                shutil.copyfile(stage/name,ROOT/name)
                if not (backup/name).exists():os.chmod(ROOT/name,0o644)
            run('docker','start',*WORKERS,timeout=120)
            workers_stopped=False
            wait_workers()
            for w in WORKERS:
                run('docker','exec',w,'grep','-q','BEONMEET_BOUNDED_FINALIZATION_V1',BOT_JS)
                run('docker','exec',w,'grep','-q','BEONMEET_DURABLE_HANDOFF_V1',UPLOADER_JS)
            run('systemctl','start',CONTROLLER,timeout=60)
            controller_stopped=False
            h=wait_controller()
            camcam_guard()
            print('CONCURRENT_RELEASE_DEPLOYED',release,{'healthy_workers':h.get('healthy_free_workers'),'authenticated_workers':h.get('authenticated_free_workers'),'pending_deliveries':h.get('pending_delivery_jobs')},flush=True)
        except Exception as exc:
            print('CUTOVER_FAILED',type(exc).__name__,flush=True)
            if changed:
                # Never roll back a running customer lane, even if subsequent
                # health verification fails after admissions reopened.
                if not controller_stopped:
                    try:guard(health=False)
                    except Exception:
                        print('ROLLBACK_BLOCKED_BY_LIVE_ACTIVITY',flush=True)
                        raise
                    run('systemctl','stop',CONTROLLER,timeout=60)
                    controller_stopped=True
                if not workers_stopped:
                    guard(health=False)
                    run('docker','stop','--time','15',*WORKERS,timeout=120)
                overlay.write_bytes((backup/'bot.before.js').read_bytes())
                for w in WORKERS:
                    run('docker','cp',str(backup/(w+'.uploader.js')),w+':'+UPLOADER_JS)
                for name in FILES:
                    saved=backup/name
                    if saved.is_file():shutil.copyfile(saved,ROOT/name)
                    elif (ROOT/name).is_file():
                        # Only the newly added code helper (not user data).
                        (ROOT/name).unlink()
                run('docker','start',*WORKERS,timeout=120)
                wait_workers()
                print('CODE_ROLLED_BACK',flush=True)
            if controller_stopped:run('systemctl','start',CONTROLLER,timeout=60)
            raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('release')
    main(parser.parse_args().release)
