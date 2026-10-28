"""Queue or inspect an isolated simulated operator action without exposing keys."""
import argparse
import json
from .human_control import Ledger, read_key

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True);p.add_argument('--key-file',required=True)
    p.add_argument('--event',required=True);p.add_argument('--step',choices=['CLAIM','HANDLE','CLOSE','STATE'],required=True)
    a=p.parse_args();ledger=Ledger(a.db,read_key(a.key_file))
    if a.step=='STATE':result=ledger.state_of(a.event+':1')
    else:
        result=ledger.queue(dict(request_id=a.event+'-'+a.step,event_id=a.event,revision=1,
             step=a.step,actor='sim-operator',note='simulation only',verified=a.step=='CLOSE'))
    print(json.dumps(result))
if __name__=='__main__':main()
