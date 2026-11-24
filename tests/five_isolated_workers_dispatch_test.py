#!/usr/bin/env python3
"""Verify five independently addressed one-slot recording workers can run concurrently.

This tests the REAL controller's dispatch functions extracted from app/main.py,
not a mock implementation of the routing logic. It cannot prove five Google
Meet browser recordings or replace a five-room end-to-end acceptance test.
"""
from __future__ import annotations
import ast
import asyncio
import datetime
import types
import typing
import uuid
from pathlib import Path

source=(Path(__file__).resolve().parents[1]/"app/main.py").read_text()
tree=ast.parse(source)
functions=[node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
           and node.name in ("_dispatch_meeting","_dispatch_meeting_serialized")]
assert len(functions)==2, "Dispatch code changed; update test"
body=compile(ast.Module(body=functions,type_ignores=[]),"app/main.py","exec")

WORKERS=[f"http://isolated-recorder-{i}:3000" for i in range(1,6)]

class Response:
    def __init__(self,code=200,data=None):
        self.status_code=code
        self.data=data or {}
        self.text=""
    def raise_for_status(self):
        if self.status_code>=400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self.data

class FakeClient:
    # Each URL represents an isolated Chrome + worker with one real slot.
    active={w:0 for w in WORKERS}
    started=[]
    def __init__(self,**kw):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self,*args):
        return False
    async def get(self,url,**kw):
        base=url.split("/capacity")[0]
        assert base in self.active,base
        return Response(200,{"data":{"runningJobs":self.active[base],"maxConcurrentJobs":1,"availableSlots":1-self.active[base]}})
    async def post(self,url,**kw):
        base=url.split("/google/join")[0]
        if self.active[base]:
            return Response(409)
        self.active[base]+=1
        self.started.append((base,kw["json"]["eventId"],kw["json"]["teamId"]))
        await asyncio.sleep(.001)
        return Response(202)

async def run():
    async def save_state():
        return None
    state={"launched_events":{}}
    env={
        "Any":typing.Any,
        "uuid":uuid,
        "datetime":datetime.datetime,
        "timezone":datetime.timezone,
        "BOT_DISPLAY_NAME":"Five-room test recorder",
        "PREMIUM_WORKER_URLS":[WORKERS[0]],
        "FREE_WORKER_URLS":WORKERS[1:],
        "SHARED_CHROME_MAX_ACTIVE":1,
        "WORKER_AUTH_GUARD_ENABLED":False,
        "_recorder_auth_ready":lambda url: True,
        "shared_chrome_dispatch_lock":asyncio.Lock(),
        "httpx":types.SimpleNamespace(AsyncClient=FakeClient),
        "state":state,
        "save_state":save_state,
    }
    exec(body,env)
    dispatch=env["_dispatch_meeting"]
    participant={"chat_id":"demo-user"}
    def event(i):
        return {"id":f"qa-meeting-{i}"}
    def url(i):
        return f"https://meet.google.com/qa{i}-room-xyz"

    results=await asyncio.gather(*[
        dispatch(event(i),participant,url(i),True) for i in range(1,6)
    ])
    assert all(result[0] for result in results),results
    assert len(FakeClient.started)==5,FakeClient.started
    assert len({target for target,_,_ in FakeClient.started})==5,FakeClient.started
    assert sum(FakeClient.active.values())==5,FakeClient.active
    assert len(state["launched_events"])==5
    assert all(item["status"]=="joining" for item in state["launched_events"].values())
    print("FIVE_INDEPENDENT_ONE_SLOT_WORKERS_LAUNCH_5_OF_5_PASS")

    result=await dispatch(event(6),participant,url(6),True)
    assert result[0] is False and result[1] is True,result
    assert len(FakeClient.started)==5
    print("SIXTH_MEETING_QUEUES_WHEN_ALL_5_PHYSICALLY_BUSY_PASS")

    # A one-worker setup MUST NOT advertise 5 despite worker max=5.
    FakeClient.active={WORKERS[0]:0}
    env["PREMIUM_WORKER_URLS"]=[WORKERS[0]]
    env["FREE_WORKER_URLS"]=[WORKERS[0]]
    first=await dispatch(event(7),participant,url(7),True)
    second=await dispatch(event(8),participant,url(8),True)
    assert first[0] and not second[0] and second[1]
    print("SHARED_CHROME_LIMIT_1_REMAINS_FAIL_CLOSED_PASS")

    # Auth-aware routing must not assign a user to a browser whose Google
    # session expired even though /health and /capacity still report OK.
    FakeClient.active={w:0 for w in WORKERS}
    FakeClient.started=[]
    env["PREMIUM_WORKER_URLS"]=WORKERS
    env["FREE_WORKER_URLS"]=WORKERS
    env["WORKER_AUTH_GUARD_ENABLED"]=True
    env["_recorder_auth_ready"]=lambda url: url==WORKERS[1]
    verified=await dispatch(event(9),participant,url(9),True)
    assert verified[0] and verified[2]=="premium-2",verified
    assert FakeClient.started[0][0]==WORKERS[1],FakeClient.started
    blocked=await dispatch(event(10),participant,url(10),True)
    assert not blocked[0] and blocked[1],blocked
    assert len(FakeClient.started)==1
    print("STALE_GOOGLE_AUTH_WORKERS_SKIPPED_AND_QUEUED_PASS")


asyncio.run(run())
