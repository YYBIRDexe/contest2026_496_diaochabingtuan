"""Expose the loopback simulation to one specified Gemini IP; no real motion."""
import argparse
import ipaddress
import json
import select
import socket
import socketserver
import threading
from .robot_simulator import Fleet, make_server

class RestrictedRelay(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    def __init__(self,address,allowed,target):
        self.allowed,self.target=allowed,target
        super().__init__(address,RelayHandler)
    def verify_request(self,request,client):
        return client[0]==self.allowed

class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(self.server.target,timeout=5) as upstream:
            sockets=[self.request,upstream]
            while True:
                readable,_,_=select.select(sockets,[],[],8)
                if not readable:return
                for source in readable:
                    data=source.recv(8192)
                    if not data:return
                    (upstream if source is self.request else self.request).sendall(data)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True);p.add_argument('--bind',required=True)
    p.add_argument('--board',required=True);p.add_argument('--port',type=int,default=18140)
    args=p.parse_args()
    for value in (args.bind,args.board):
        ip=ipaddress.IPv4Address(value)
        if not ip.is_private or ip.is_loopback:raise ValueError('private LAN IPv4 required')
    fleet=make_server(Fleet(args.database))
    worker=threading.Thread(target=fleet.serve_forever,daemon=True);worker.start()
    try:
        with RestrictedRelay((args.bind,args.port),args.board,fleet.server_address) as relay:
            print(json.dumps({'source':'PC_SIMULATION_ONLY','endpoint':list(relay.server_address),
                              'allowed_board':args.board,'motion':False}),flush=True)
            relay.serve_forever()
    finally:
        fleet.shutdown();fleet.server_close();worker.join()

if __name__=='__main__':main()
