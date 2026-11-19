#!/usr/bin/env python3
"""The unverified All Meetings feature is not marketed, cannot auto-join, and is not re-enabled silently."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

root=Path(__file__).resolve().parents[1]
main=(root/'app/main.py').read_text(encoding='utf-8')
i18n=(root/'app/i18n.py').read_text(encoding='utf-8')
mod=ast.parse(main)
assert 'AUTO_ALL_MEETINGS_ENABLED = os.environ.get("AUTO_ALL_MEETINGS_ENABLED", "false")' in main
assert 'auto_settings = dict(state.setdefault("auto_join_all", {})) if AUTO_ALL_MEETINGS_ENABLED else {}' in main
assert 'if not AUTO_ALL_MEETINGS_ENABLED:' in main
assert 'raise HTTPException(status_code=404, detail="Personal automatic Calendar recording is temporarily unavailable")' in main
assert 'state.setdefault("auto_join_all", {})[str(chat_id)] = False' in main
assert '"command": "auto", "description":' not in main
assert '{"text": labels["auto"]}' not in main
assert 'AUTO_ALL_MEETINGS_ENABLED and bool(state.setdefault("auto_join_all", {}).get(str(chat_id)))' in main
assert 'if oauth_chat_id and not AUTO_ALL_MEETINGS_ENABLED:' in main[main.find('async def auth_google_callback'):]

spec=importlib.util.spec_from_file_location('i18n', root/'app/i18n.py')
lang=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(lang)
functions={n.name:n for n in mod.body if isinstance(n,ast.FunctionDef)}
def extracted(name,env):
    node=functions[name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'app/main.py','exec'),env)
    return env[name]
menu=extracted('telegram_reply_keyboard',{'i18n_menu':lang.menu,'user_language':lambda _: 'fa','ADMINUSER':''})
keys=menu('42')['keyboard']
assert all('همه جلسات' not in button['text'] for row in keys for button in row)
assert all('All meetings' not in button['text'] for row in keys for button in row)
on=extracted('auto_join_enabled',{'AUTO_ALL_MEETINGS_ENABLED':False,'state':{'auto_join_all':{'42':True}}})
assert on('42') is False
for language in lang.SUPPORTED_LANGUAGES:
    assert lang.MESSAGES[language]['auto_unavailable']
    assert lang.MESSAGES[language]['manual_mode_notice']
    assert not any('auto'==cmd for cmd in lang.PROFILE_TEXT[language]['commands'])
    offer=lang.MESSAGES[language]['premium_offer']
    forbidden={'fa':'اتصال Calendar و ورود خودکار به همه جلسات','en':'Connect Calendar and automatically join all meetings','de':'Alle Meetings ist aktiviert'}
    assert forbidden[language] not in offer
assert 'Connect Google Calendar once. BeOnMeet detects' not in main
assert 'برای تشخیص خودکار جلسات، امکان اتصال' not in main
print('ALL_MEETINGS_HIDDEN_TEST_PASS')
