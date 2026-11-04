"""Isolated local acceptance receiver and operator; not the physical platform."""
import argparse
import json
import threading
from .human_control import read_key
from .receiver import make_server
from .operator_server import make_operator_server

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--db',required=True);p.add_argument('--key-file',required=True)
 p.add_argument('--receiver-port',type=int,default=18142)
 p.add_argument('--operator-port',type=int,default=18143)
 args=p.parse_args()
 key=read_key(args.key_file)
 receiver=make_server(args.db,args.receiver_port,control_key=key)
 operator=make_operator_server(args.db,key,args.operator_port)
 t=threading.Thread(target=receiver.serve_forever,daemon=True);t.start()
 print(json.dumps({'source':'VM_SIMULATED_PLATFORM','receiver':args.receiver_port,
                   'operator':args.operator_port,'motion':False}),flush=True)
 try:operator.serve_forever()
 finally:
  receiver.shutdown();receiver.server_close();operator.server_close();t.join()
if __name__=='__main__':main()
