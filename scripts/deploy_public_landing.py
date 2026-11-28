"""Install the reviewed public pages while preserving production controller differences."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

root = Path("/opt/beonmeet")
os.chdir(root)
release = sys.argv[1]
base = "a1fbaef5016d8e545255d739eefb37a276a98cfc"
paths = ["app/main.py", "app/landing_page.py", *["app/landing_assets/" + n for n in
         ("page.html", "style.css", "vazir.woff2", "OFL.txt")]]
backup = Path(tempfile.mkdtemp(prefix=".landing-backup-", dir=root))

def blob(rev, path):
    return subprocess.check_output(["git", "show", rev + ":" + path])

def idle():
    with urlopen("http://127.0.0.1:8109/health", timeout=5) as r:
        health = json.load(r)
    assert health["ok"] and not any(health[k] for k in ("free_queue","premium_queue","active_delivery_jobs","pending_delivery_jobs","active_recording_jobs")), "Production work in flight"
    for port in (9124,9126,9132,9133,9134,9135):
        with urlopen(f"http://127.0.0.1:{port}/capacity", timeout=5) as r:
            data=json.load(r)
        assert int((data.get("data") or data)["runningJobs"]) == 0, "Worker in use"

for name in paths:
    original = Path(name)
    if original.exists():
        shutil.copy2(original, backup / (original.name + ".before"))
    target = backup / original.name
    target.write_bytes(blob(release, name))
    if name == "app/main.py":
        parent = backup / "main.base"
        parent.write_bytes(blob(base, name))
        merged = subprocess.check_output(["git", "merge-file", "-p", str(original), str(parent), str(target)])
        target.write_bytes(merged)
    if name.endswith(".py"):
        compile(target.read_bytes(), name, "exec")

def replace(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
        f.write(source.read_bytes())
    os.chmod(f.name, 0o644)
    os.replace(f.name, target)

idle()
changed = []
restarted = False
try:
    for name in reversed(paths):
        replace(backup / Path(name).name, Path(name))
        changed.append(name)
    idle()
    restarted = True
    subprocess.run(["systemctl","restart","beonmeet-controller"],check=True)
    for attempt in range(30):
        try:
            with urlopen("http://127.0.0.1:8109/fa",timeout=3) as r:
                assert b'class="illustration"' in r.read()
            break
        except OSError:
            if attempt == 29:
                raise
            time.sleep(1)
except Exception:
    for name in changed:
        old=backup / (Path(name).name + ".before")
        if old.exists():
            replace(old,Path(name))
        else:
            Path(name).unlink(missing_ok=True)
    if restarted:
        subprocess.run(["systemctl","restart","beonmeet-controller"],check=True)
    raise
print("LANDING_LIVE",release)
