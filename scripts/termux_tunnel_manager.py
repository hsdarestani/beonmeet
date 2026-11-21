#!/usr/bin/env python3
"""Temporary SSH -N localhost:6081 tunnel only, with no shell or root access."""
from __future__ import annotations

import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

USER = "beonmeet-tunnel"
HOME = Path("/var/lib/beonmeet-tunnel")
AUTHORIZED = HOME / ".ssh" / "authorized_keys"
SSHD_CONF = Path("/etc/ssh/sshd_config")
MANAGER_ROOT = Path("/opt/beonmeet/.restricted-termux")
LOCK = Path("/var/lock/pars-vds-bot-deploy.lock")
PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIITcnQyfmkD2kVcyuRbwBqiHYoprFYMgMPSjB7hi82zz"
ALLOWED = 'restrict,port-forwarding,permitopen="127.0.0.1:6081"'
BLOCK_START = "# BEONMEET_TUNNEL_ONLY_BEGIN_20261121\n"
BLOCK_END = "# BEONMEET_TUNNEL_ONLY_END_20261121\n"
BLOCK = (
    BLOCK_START
    + "Match User beonmeet-tunnel\n"
    + "    AuthenticationMethods publickey\n"
    + "    PasswordAuthentication no\n"
    + "    KbdInteractiveAuthentication no\n"
    + "    PubkeyAuthentication yes\n"
    + "    AllowTcpForwarding local\n"
    + "    PermitOpen 127.0.0.1:6081\n"
    + "    X11Forwarding no\n"
    + "    AllowAgentForwarding no\n"
    + "    PermitTTY no\n"
    + "    PermitTunnel no\n"
    + "    AllowStreamLocalForwarding no\n"
    + "    GatewayPorts no\n"
    + "    MaxSessions 0\n"
    + "    ForceCommand /usr/sbin/nologin\n"
    + BLOCK_END
)
EXPIRE_AFTER = "24h"


def run(args: list[str], *, timeout: int = 25, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=check)


def write_config(text: str) -> None:
    st = SSHD_CONF.stat()
    handle, path = tempfile.mkstemp(prefix=".beonmeet-sshd-", dir=str(SSHD_CONF.parent))
    tmp = Path(path)
    try:
        with os.fdopen(handle, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.replace(tmp, SSHD_CONF)
    finally:
        tmp.unlink(missing_ok=True)


def reload_sshd() -> None:
    run(["/usr/sbin/sshd", "-t"])
    run(["systemctl", "reload", "ssh"])


def no_other_root_effects(before: dict[str, str]) -> None:
    for person in ("root", "risheupload"):
        new = sshd_policy(person)
        if new != before[person]:
            raise RuntimeError("SSH policy changed for existing users")


def sshd_policy(person: str) -> dict[str, str]:
    result = run(["/usr/sbin/sshd", "-T", "-C", f"user={person},host=localhost,addr=127.0.0.1"])
    return dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)


def verify_policy() -> None:
    p = sshd_policy(USER)
    expected = {
        "authenticationmethods": "publickey",
        "passwordauthentication": "no",
        "kbdinteractiveauthentication": "no",
        "pubkeyauthentication": "yes",
        "allowtcpforwarding": "local",
        "permitopen": "127.0.0.1:6081",
        "x11forwarding": "no",
        "allowagentforwarding": "no",
        "permittty": "no",
        "permittunnel": "no",
        "maxsessions": "0",
        "forcecommand": "/usr/sbin/nologin",
    }
    for key, value in expected.items():
        if p.get(key) != value:
            raise RuntimeError(f"SSH tunnel guard does not match: {key}")
    if not AUTHORIZED.is_file():
        raise RuntimeError("SSH public key missing")
    contents = AUTHORIZED.read_text().strip().splitlines()
    if contents != [ALLOWED + " " + PUBKEY]:
        raise RuntimeError("Authorized keys contain unexpected entries")
    if stat.S_IMODE(AUTHORIZED.stat().st_mode) != 0o600:
        raise RuntimeError("Authorized keys permissions unsafe")
    if stat.S_IMODE(HOME.stat().st_mode) != 0o700:
        raise RuntimeError("Tunnel home not private")


def live_forward_test() -> None:
    """Check an ephemeral key can forward 6081 and cannot execute a shell."""
    with tempfile.TemporaryDirectory(prefix=".termux-tunnel-test-", dir=str(MANAGER_ROOT)) as d:
        tmp = Path(d)
        priv = tmp / "testkey"
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(priv)])
        public = (tmp / "testkey.pub").read_text().strip()
        opts = ALLOWED + " " + " ".join(public.split()[:2])
        AUTHORIZED.write_text(ALLOWED + " " + PUBKEY + "\n" + opts + "\n")
        os.chmod(AUTHORIZED, 0o600)
        command = [
            "ssh", "-4", "-N",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={tmp / 'known_hosts'}",
            "-o", "ConnectTimeout=8",
            "-o", "LogLevel=ERROR",
            "-i", str(priv),
            "-p", "9011",
            "-L", "127.0.0.1:16081:127.0.0.1:6081",
            f"{USER}@127.0.0.1",
        ]
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            success = False
            for _ in range(35):
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen("http://127.0.0.1:16081/vnc.html", timeout=2) as response:
                        if response.status == 200:
                            success = True
                            break
                except Exception:
                    pass
                time.sleep(0.35)
            if not success:
                raise RuntimeError("Real forwarding test did not establish private Chrome access")
            print("LIVE_LOCAL_FORWARDING_TO_PRIVATE_CHROME_VERIFIED", flush=True)
            # A session channel should be denied even with a valid key.
            cmd = [
                "ssh", "-4", "-T", "-o", "BatchMode=yes",
                "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", f"UserKnownHostsFile={tmp / 'known_hosts'}",
                "-o", "ConnectTimeout=5",
                "-o", "LogLevel=ERROR",
                "-i", str(priv), "-p", "9011",
                f"{USER}@127.0.0.1", "true",
            ]
            shell = run(cmd, timeout=10, check=False)
            if shell.returncode == 0:
                raise RuntimeError("Restricted account unexpectedly allowed command execution")
            print("SSH_COMMAND_EXECUTION_BLOCKED", flush=True)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            AUTHORIZED.write_text(ALLOWED + " " + PUBKEY + "\n")
            os.chmod(AUTHORIZED, 0o600)


def setup() -> None:
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError("A tunnel user already exists; refusing to change existing account")
    conf = SSHD_CONF.read_text()
    if BLOCK_START in conf or BLOCK_END in conf:
        raise RuntimeError("Tunnel SSH configuration already installed")
    run(["/usr/sbin/sshd", "-t"])
    before = {u:sshd_policy(u) for u in ("root", "risheupload")}
    for path in ("/usr/sbin/nologin", "/usr/sbin/useradd"):
        if not Path(path).exists():
            raise RuntimeError("Required system account tool is unavailable")
    with urllib.request.urlopen("http://127.0.0.1:6081/vnc.html", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Existing private Chrome is not healthy")
    created = False
    config_changed = False
    try:
        run(["/usr/sbin/useradd", "--system", "--create-home", "--home-dir", str(HOME),
             "--shell", "/usr/sbin/nologin", "--user-group", USER])
        created = True
        run(["/usr/sbin/usermod", "-L", USER])
        st = pwd.getpwnam(USER)
        os.chmod(HOME, 0o700)
        ssh_dir = HOME / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=False)
        AUTHORIZED.write_text(ALLOWED + " " + PUBKEY + "\n")
        os.chmod(AUTHORIZED, 0o600)
        for folder in (HOME, ssh_dir):
            os.chown(folder, st.pw_uid, st.pw_gid)
        os.chown(AUTHORIZED, st.pw_uid, st.pw_gid)
        write_config(conf + ("\n" if not conf.endswith("\n") else "") + BLOCK)
        config_changed = True
        reload_sshd()
        no_other_root_effects(before)
        verify_policy()
        print("TUNNEL_USER_RESTRICTED_POLICY_VERIFIED", flush=True)
        live_forward_test()
        verify_policy()
        if not (MANAGER_ROOT / "manager.py").is_file():
            raise RuntimeError("Expiry script not installed at expected destination")
        run([
            "systemd-run", "--quiet",
            "--unit=beonmeet-termux-tunnel-expiry",
            "--on-active=" + EXPIRE_AFTER,
            "/usr/bin/python3", str(MANAGER_ROOT / "manager.py"), "expire",
        ])
        fp = run(["ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub"]).stdout.strip()
        # Host fingerprint is public and helps verify the first Termux login.
        match = re.search(r"(SHA256:[^\s]+)", fp)
        print("SSH_HOST_ED25519_FINGERPRINT", match.group(1) if match else "unavailable", flush=True)
        print("TERMUX_RESTRICTED_TUNNEL_ACTIVE", flush=True)
        print("TUNNEL_ACCOUNT_AUTO_EXPIRY", EXPIRE_AFTER, flush=True)
    except Exception:
        if config_changed:
            try:
                write_config(conf)
                reload_sshd()
            except Exception:
                print("CRITICAL_SSHD_CONFIG_ROLLBACK_REQUIRES_MANUAL_REVIEW", flush=True)
        if created:
            try:
                run(["/usr/sbin/userdel", "--remove", USER], timeout=20)
            except Exception:
                print("TUNNEL_ACCOUNT_CLEANUP_REQUIRES_REVIEW", flush=True)
        raise


def expire() -> None:
    text = SSHD_CONF.read_text()
    if BLOCK_START not in text or BLOCK_END not in text:
        print("TERMUX_TUNNEL_SSHD_BLOCK_ALREADY_ABSENT", flush=True)
    else:
        if text.count(BLOCK_START) != 1 or text.count(BLOCK_END) != 1:
            raise RuntimeError("Refuse unknown SSH configuration structure")
        head, tail = text.split(BLOCK_START, 1)
        _, rest = tail.split(BLOCK_END, 1)
        new_text = head + rest
        write_config(new_text)
        try:
            reload_sshd()
        except Exception:
            write_config(text)
            reload_sshd()
            raise
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        # Only this explicitly dedicated tunnel account may be removed.
        run(["/usr/sbin/userdel", "--force", "--remove", USER], timeout=20)
    print("TEMPORARY_TERMUX_TUNNEL_EXPIRED_AND_ACCOUNT_DELETED", flush=True)


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    if len(sys.argv) != 2 or sys.argv[1] not in ("setup", "expire"):
        raise RuntimeError("Use setup or expire")
    MANAGER_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(MANAGER_ROOT, 0o700)
    with LOCK.open("a+") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        if sys.argv[1] == "setup":
            setup()
        else:
            expire()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TERMUX_TUNNEL_ERROR_CLASS", type(exc).__name__, str(exc)[:110], flush=True)
        sys.exit(1)
