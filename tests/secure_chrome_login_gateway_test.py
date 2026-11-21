#!/usr/bin/env python3
"""Offline smoke test of short-lived authenticated Chrome gateway."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

here=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("gateway",here/"scripts/secure_chrome_login_gateway.py")
gateway=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gateway)

with TemporaryDirectory() as folder:
    root=Path(folder)
    gate=root/"secret-gateway"
    gate.mkdir()
    orig="server {\n    listen 443 ssl;\n    server_name beonmeet.smarbiz.sbs;\n    location / {\n        proxy_pass http://127.0.0.1:8109;\n    }\n}\n"
    path=root/"nginx.conf"
    path.write_text(orig)
    messages=[]
    command_calls=[]
    with mock.patch.object(gateway,"SITE",path), \
         mock.patch.object(gateway,"ROOT",gate), \
         mock.patch.object(gateway,"STATE",gate/"active.json"), \
         mock.patch.object(gateway,"MANAGER",gate/"manager.py"), \
         mock.patch.object(gateway,"health",lambda:None), \
         mock.patch.object(gateway,"read_bot_config",lambda:("x"*40,"https://api.telegram.org")), \
         mock.patch.object(gateway,"owner_chat_id",lambda:"999999"), \
         mock.patch.object(gateway,"send_telegram",lambda msg:messages.append(msg)), \
         mock.patch.object(gateway,"execute",lambda args:command_calls.append(args)), \
         mock.patch.object(gateway,"probe",lambda route,pwd:401 if pwd is None else 200), \
         mock.patch.object(gateway.os,"chown",lambda *args:None), \
         mock.patch.object(gateway.grp,"getgrnam",lambda group:SimpleNamespace(gr_gid=33)):
        gateway.setup()
        active=(gate/"active.json")
        assert active.exists()
        assert (path.read_text().count("auth_basic_user_file") == 1)
        assert "location ^~ /beonmeet-login-" in path.read_text()
        assert "access_log off" in path.read_text()
        assert len(messages)==1 and "https://beonmeet.smarbiz.sbs/" in messages[0]
        assert "رمز موقت:" in messages[0] and "رمز Google را برای کسی نفرست" in messages[0]
        assert not any("رمز موقت:" in str(x) for x in command_calls)
        assert any("systemd-run" in args for args in command_calls)
        try:
            gateway.setup()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Concurrent setup must be rejected")
        gateway.cleanup_unlocked()
        assert path.read_text()==orig
        assert not active.exists()
        assert not list(gate.glob("*.htpasswd"))
        gateway.cleanup_unlocked()
        # Simulate Telegram failure after proxy setup; must remove gateway.
        with mock.patch.object(gateway,"send_telegram",side_effect=RuntimeError("simulate")):
            try:
                gateway.setup()
            except RuntimeError:
                pass
            else:
                raise AssertionError("Telegram delivery failure must fail closed")
        assert path.read_text()==orig and not active.exists()
        assert not list(gate.glob("*.htpasswd"))
print("SECURE_EPHEMERAL_CHROME_LOGIN_GATEWAY_TEST_PASS")
