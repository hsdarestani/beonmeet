#!/usr/bin/env python3
"""Fail-closed production controller auth guard regression using real source AST."""
import ast,datetime,json,tempfile,typing
from pathlib import Path
root=Path(__file__).resolve().parents[1]
code=(root/'app/main.py').read_text()
tree=ast.parse(code)
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_recorder_auth_ready')
module=compile(ast.Module(body=[fn],type_ignores=[]),'app/main.py','exec')
with tempfile.TemporaryDirectory() as td:
    file=Path(td)/'auth-status.json'
    env={
        'WORKER_AUTH_GUARD_ENABLED':True,
        'WORKER_AUTH_STATE_FILE':file,
        'WORKER_AUTH_MAX_AGE_SECONDS':360,
        'json':json,
        'datetime':datetime.datetime,
        'timezone':datetime.timezone,
    }
    exec(module,env)
    check=env['_recorder_auth_ready']
    url='http://127.0.0.1:9132'
    now=datetime.datetime.now(datetime.timezone.utc).timestamp()
    assert check(url) is False,'Missing status must fail closed'
    def put(ready,age):
        file.write_text(json.dumps({'workers':{url:{'ready':ready,'checked_at':now-age}}}))
    put(True,0)
    assert check(url) is True
    put(False,0)
    assert check(url) is False
    put(True,370)
    assert check(url) is False,'Stale auth may not dispatch'
    put(True,-100)
    assert check(url) is False,'Future timestamp may not dispatch'
    file.write_text('corrupt')
    assert check(url) is False
    env['WORKER_AUTH_GUARD_ENABLED']=False
    assert check(url) is True
print('PRODUCTION_RECORDER_AUTH_FAIL_CLOSED_AGE_AND_GUEST_GATES_PASS')
