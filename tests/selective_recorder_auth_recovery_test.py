#!/usr/bin/env python3
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from recover_selected_recorder_sessions import select
ports=(9126,9132,9133,9134,9135)
def key(p):return 'http://127.0.0.1:'+str(p)
state={key(p):{'ready':i in (1,4),'checked_at':1000} for i,p in enumerate(ports)}
caps={p:{'runningJobs':0,'availableSlots':1} for p in ports}
assert select(ports,state,caps,1010)==[9132,9126,9133,9134]
caps[9132]={'runningJobs':1,'availableSlots':0}
assert select(ports,state,caps,1010)==[9135,9126,9133,9134]
caps[9133]={'runningJobs':1,'availableSlots':0}
assert select(ports,state,caps,1010)==[9135,9126,9134]
caps[9135]={'runningJobs':1,'availableSlots':0}
assert select(ports,state,caps,1010)==[9126,9134]
for p in ports:state[key(p)]={'ready':True,'checked_at':1010}
assert select(ports,state,caps,1010)==[]
print('SELECTIVE_RECOVERY_IDLE_ONLY_SOURCE_AND_TARGETS_PASS')
