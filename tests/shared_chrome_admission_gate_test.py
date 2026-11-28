#!/usr/bin/env python3
"""Verify shared Chrome joining is serial even for two concurrent /now calls."""
import ast
import asyncio
from contextlib import nullcontext
import datetime
import types
import typing
import uuid
from pathlib import Path

source=(Path(__file__).resolve().parents[1]/"app/main.py").read_text()
tree=ast.parse(source)
defns=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in ("_dispatch_meeting","_dispatch_meeting_serialized")]
assert len(defns)==2
code=compile(ast.Module(body=defns,type_ignores=[]),"app/main.py","exec")
assert 'SHARED_CHROME_MAX_ACTIVE = max(0, min(16' in source
assert "client.get(f\"{base_url}/capacity\"" in source
assert "if currently_running >= SHARED_CHROME_MAX_ACTIVE:" in source
assert "async with shared_chrome_dispatch_lock:" in source

class Response:
    def __init__(self,code,body=None):
        self.status_code=code
        self.body=body or {}
        self.text=""
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError("down")
    def json(self):return self.body

class FakeClient:
    state={"active":0,"posts":0,"gets":0,"capacity_fails":False}
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def get(self,url,**kwargs):
        s=type(self).state
        s["gets"]+=1
        if s["capacity_fails"]:raise RuntimeError("capacity unavailable")
        return Response(200,{"data":{"runningJobs":s["active"]}})
    async def post(self,url,**kwargs):
        s=type(self).state
        s["posts"]+=1
        await asyncio.sleep(.001)
        s["active"]+=1
        return Response(202)

async def check():
    state={"launched_events":{}}
    async def save_state():pass
    async def reserve_recording_seconds(*args):return 3600
    env={
        "Any":typing.Any,
        "uuid":uuid,
        "datetime":datetime.datetime,
        "timezone":datetime.timezone,
        "BOT_DISPLAY_NAME":"Recorder",
        "PREMIUM_WORKER_URLS":["http://chrome"],
        "FREE_WORKER_URLS":["http://chrome"],
        "SHARED_CHROME_MAX_ACTIVE":1,
        "WORKER_AUTH_GUARD_ENABLED":False,
        "_worker_auth_dispatch_lease": lambda url: nullcontext(True),
        "_recorder_auth_ready":lambda url: True,
        "shared_chrome_dispatch_lock":asyncio.Lock(),
        "httpx":types.SimpleNamespace(AsyncClient=FakeClient),
        "state":state,
        "save_state":save_state,
        "reserve_recording_seconds":reserve_recording_seconds,
    }
    exec(code,env)
    dispatch=env["_dispatch_meeting"]
    def event(n):return {"id":f"event-{n}"}
    user={"chat_id":"123456"}
    FakeClient.state={"active":0,"posts":0,"gets":0,"capacity_fails":False}
    outcomes=await asyncio.gather(
        dispatch(event(1),user,"https://meet.google.com/aaa-bbbb-ccc",True),
        dispatch(event(2),user,"https://meet.google.com/ddd-eeee-fff",True)
    )
    assert sum(bool(item[0]) for item in outcomes)==1,outcomes
    assert sum(bool(item[1]) for item in outcomes)==1,outcomes
    assert FakeClient.state["posts"]==1,FakeClient.state
    assert FakeClient.state["gets"]==2,FakeClient.state
    assert len(state["launched_events"])==1
    assert next(iter(state["launched_events"].values()))["status"]=="joining"

    FakeClient.state={"active":0,"posts":0,"gets":0,"capacity_fails":True}
    outcome=await dispatch(event(3),user,"https://meet.google.com/aaa-bbbb-ccc",True)
    assert outcome[:2]==(False,True),outcome
    assert FakeClient.state["posts"]==0

    # Operator can explicitly disable guard after isolated-browser QA.
    env["SHARED_CHROME_MAX_ACTIVE"]=0
    FakeClient.state={"active":0,"posts":0,"gets":0,"capacity_fails":False}
    outcome=await dispatch(event(4),user,"https://meet.google.com/aaa-bbbb-ccc",True)
    assert outcome[0] and FakeClient.state["gets"]==0 and FakeClient.state["posts"]==1
    print("SHARED_CHROME_SERIAL_QUEUE_AND_FAIL_CLOSED_TEST_PASS")
asyncio.run(check())
