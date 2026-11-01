"""Verify real Git HTTPS and SSH proxy transports; never change repo data or keys."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import threading
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from storage import atomic_json
environment={k:v for k,v in os.environ.items() if k.upper() not in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')}
environment.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
report={'time':time.time(),'https_environment_proxy_cleared':True}
def git_test():
    env=dict(environment,GIT_TRACE_CURL='1',GIT_TRACE_CURL_NO_DATA='1')
    result=subprocess.run(['git','-c','credential.helper=','ls-remote','https://github.com/git/git.git','HEAD'],
                          env=env,capture_output=True,timeout=70,creationflags=0x08000000)
    trace=result.stderr.decode('utf-8','replace')
    return {'exit':result.returncode,'head_ref_returned':bool(re.match(rb'[0-9a-f]{40}\s+HEAD',result.stdout)),
            'connected_to_local_proxy':bool(re.search(r'(?:127\.0\.0\.1|localhost).*18790',trace)),
            'connect_to_github_seen':'CONNECT github.com:443' in trace}
def ssh_test():
    expected=False;config_error=''
    client=Path(r'C:\Program Files\Git\usr\bin\ssh.exe')
    args=[str(client) if client.exists() else 'ssh','-G','github.com']
    try:
        cfg=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=8,creationflags=0x08000000)
        settings={line.split(' ',1)[0]:line.split(' ',1)[1] for line in cfg.stdout.splitlines() if ' ' in line}
        expected=settings.get('hostname')=='ssh.github.com' and settings.get('port')=='443' and 'suioo-github-connect.py' in settings.get('proxycommand','')
    except Exception as error:config_error=str(error)
    python=Path(sys.executable).with_name('python.exe')
    child=subprocess.Popen([str(python),str(Path.home()/'.ssh/suioo-github-connect.py'),'ssh.github.com','443'],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
    banner=[]
    reader=threading.Thread(target=lambda:banner.append(child.stdout.readline()),daemon=True);reader.start()
    try:
        child.stdin.write(b'SSH-2.0-SuiooVerify\r\n');child.stdin.flush()
        reader.join(18)
    finally:
        child.kill();child.wait(timeout=5)
        reader.join(2)
    return {'ssh_config_uses_proxy':expected,'ssh_banner_through_proxy':bool(banner and banner[0].startswith(b'SSH-2.0-')),
            'authenticated_git_ssh_tested':False,'config_check_error':config_error}

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures={pool.submit(git_test):'git_https',pool.submit(ssh_test):'git_ssh'}
    for future,name in futures.items():
        try:report[name]=future.result()
        except Exception as error:report[name]={'error':str(error)}
report['finished']=time.time()
atomic_json(root/'runtime/github-verification.json',report)
print(json.dumps(report))
