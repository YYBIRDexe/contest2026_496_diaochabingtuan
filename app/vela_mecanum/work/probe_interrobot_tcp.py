import getpass,paramiko
p=getpass.getpass('Robot SSH password: ')
for source in range(1,5):
    c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(f'192.168.1.{200+source}',username='pi',password=p,timeout=8)
    try:
        print('robot',source,flush=True)
        for target in range(1,5):
            if target==source:continue
            cmd=f"timeout 3 bash -lc 'cat </dev/null >/dev/tcp/192.168.1.{200+target}/22'"
            _,o,e=c.exec_command(cmd,timeout=5)
            print(' ->',target,'exit',o.channel.recv_exit_status(),e.read().decode(errors='replace')[:100],flush=True)
    finally:c.close()
