#!/usr/bin/env python3
"""Actual controller reservation functions with five same-account demands."""
import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

root=Path(__file__).resolve().parents[1]
tree=ast.parse((root/'app/main.py').read_text())
nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in {'_dispatch_meeting','reserve_recording_seconds'}]

async def test():
    balance=18000
    state={'launched_events':{},'pending_deliveries':{}}
    async def dispatch(event, req, url, premium, reserved):
        await asyncio.sleep(.001)
        state['launched_events'][event['id']]={'chat_id':req['chat_id'],'status':'joining','reserved_seconds':reserved,'pool':'premium-1'}
        return True,False,'premium-1'
    env=dict(Any=Any,asyncio=asyncio,state=state,shared_chrome_dispatch_lock=asyncio.Lock(),
             _dispatch_meeting_serialized=dispatch,
             paid_recording_entitlement=lambda chat:{'remaining_seconds':balance},
             free_recording_entitlement=lambda chat:{'remaining_seconds':balance})
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),env)
    start=env['_dispatch_meeting']
    results=await asyncio.gather(*(start({'id':f'job-{i}'},{'chat_id':'same'},f'room-{i}',True) for i in range(6)))
    assert sum(r[0] for r in results)==5
    assert len(state['launched_events'])==5
    assert sum(x['reserved_seconds'] for x in state['launched_events'].values())==18000
    assert await env['reserve_recording_seconds']('same',True)==0
    # One delivered 20-minute meeting consumed only 1200 seconds; releasing
    # the rest enables another job or an extension on an existing job.
    state['launched_events']['job-0']['status']='delivering'
    state['pending_deliveries']['job-0']={'billing_committed':True}
    balance-=1200
    assert await env['reserve_recording_seconds']('same',True)==2400
    duplicate=await start({'id':'job-1'},{'chat_id':'same'},'room-1',True)
    assert duplicate[0] and len(state['launched_events'])==5
    state['launched_events']['job-2']['status']='failed'
    assert await env['reserve_recording_seconds']('same',True)==3600
    print('FIVE_SAME_ACCOUNT_ATOMIC_CREDIT_RESERVATION_PASS')

asyncio.run(test())
