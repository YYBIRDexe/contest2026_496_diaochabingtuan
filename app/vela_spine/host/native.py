"""Host harness calls the SAME portable C core intended for board integration."""
import ctypes as C
from pathlib import Path
import sys

class Event(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('consequence','urgency','exposure','spread','fresh')]
class Assessment(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('score','decision','unknown_mask')]
class Problem(C.Structure):
    _fields_ = [('tags', C.c_int),('robots', C.c_int),('budget', C.c_int*4),
                ('priority',C.c_int*8),('eligible',C.c_int*32),
                ('energy',C.c_int*32),('cost',C.c_int*32)]
class Allocation(C.Structure):
    _fields_ = [('owner',C.c_int*8),('uncovered_priority',C.c_int),('total_cost',C.c_int)]
LIB = C.CDLL(str(Path(__file__).resolve().parents[1]/'build'/('spine.dll' if sys.platform=='win32' else 'libspine.so')))
LIB.sp_assess.argtypes = [C.POINTER(Event),C.c_int,C.POINTER(Assessment)]
LIB.sp_allocate.argtypes = [C.POINTER(Problem),C.POINTER(Allocation)]

def assess(factors, threshold=70, fresh=True):
    values=[]
    for key in ('consequence','urgency','exposure','spread'):
        v=factors.get(key,-1)
        if type(v) is not int or not -1<=v<=5: raise ValueError('invalid factor '+key)
        values.append(v)
    if type(threshold) is not int or not 0<=threshold<=100 or type(fresh) is not bool:
        raise ValueError('invalid policy/freshness')
    result=Assessment()
    if LIB.sp_assess(C.byref(Event(*values,int(fresh))),threshold,C.byref(result)):
        raise ValueError('native assessment rejected')
    return {'score':result.score,'decision':('AUTO','HUMAN_REVIEW','IMMEDIATE_HUMAN')[result.decision],
            'unknown_mask':result.unknown_mask,'threshold':threshold,
            'comparison':'>','factors':dict(zip(('consequence','urgency','exposure','spread'),values))}

def allocate(tags, robots, edges):
    if not 0<=len(tags)<=8 or not 1<=len(robots)<=4: raise ValueError('capacity')
    ids=[t['id'] for t in tags]; rids=[r['id'] for r in robots]
    if len(set(ids))!=len(ids) or len(set(rids))!=len(rids): raise ValueError('duplicate id')
    p=Problem(); p.tags=len(tags); p.robots=len(robots)
    def integer(v,minimum,maximum):
        if type(v) is not int or not minimum<=v<=maximum: raise ValueError('invalid allocation field')
        return v
    for r,robot in enumerate(robots): p.budget[r]=integer(robot['budget'],0,1000000)
    for t,tag in enumerate(tags):
        p.priority[t]=integer(tag['priority'],1,1000)
        for r,robot in enumerate(robots):
            edge=edges.get((tag['id'],robot['id']))
            if not edge: continue
            k=t*4+r
            # Only unowned pending tasks; arbitrary reassignment is not supported.
            p.eligible[k]=int(tag.get('state')=='PENDING' and tag.get('owner') is None
                              and robot.get('fresh') is True and robot.get('ready') is True
                              and edge.get('verified') is True)
            p.energy[k]=integer(edge['energy'],0,1000000)
            p.cost[k]=integer(edge['cost'],0,1000000)
    out=Allocation()
    if LIB.sp_allocate(C.byref(p),C.byref(out)): raise ValueError('native allocation rejected')
    return {'assignments':{tag['id']:rids[out.owner[i]] if out.owner[i]>=0 else None for i,tag in enumerate(tags)},
            'uncovered_priority':out.uncovered_priority,'total_cost':out.total_cost,
            'status':'PROPOSAL_ONLY'}
