"""Pin GitHub Git HTTPS and OpenSSH traffic without changing other Git hosts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from regional import GITHUB_DOMAINS
from storage import atomic_json
proxy='http://127.0.0.1:18790'
data=root/'data';data.mkdir(exist_ok=True)
backup_path=data/'github-proxy-backup.json'
backup=json.loads(backup_path.read_text(encoding='utf-8')) if backup_path.exists() else {'time':time.time(),'git':{}}
def git(*args):return subprocess.run(['git',*args],capture_output=True,text=True,creationflags=0x08000000)
keys=[]
for domain in GITHUB_DOMAINS:
    for host in (domain,'*.'+domain):
        for scheme in ('https','http'):
            key=f'http.{scheme}://{host}/.proxy';keys.append(key)
            if key not in backup['git']:
                old=git('config','--global','--get-all',key)
                backup['git'][key]=old.stdout.splitlines() if old.returncode==0 else None
atomic_json(backup_path,backup)
for key in keys:
    result=git('config','--global','--replace-all',key,proxy)
    if result.returncode:raise RuntimeError('Failed to configure GitHub HTTPS proxy')
ssh=Path.home()/'.ssh';ssh.mkdir(exist_ok=True)
config=ssh/'config';original=config.read_text(encoding='utf-8-sig') if config.exists() else ''
saved=data/'github-ssh-config-before.txt'
if not saved.exists():saved.write_text(original,encoding='utf-8')
start='# BEGIN SUIOO GITHUB PROXY\n';end='# END SUIOO GITHUB PROXY\n'
if start in original:
    a=original.index(start);b=original.index(end,a)+len(end);original=original[:a]+original[b:]
connector=ssh/'suioo-github-connect.py';shutil.copyfile(Path(__file__).with_name('GitHub-Connect.py'),connector)
block=(start+'Host github.com ssh.github.com\n    HostName ssh.github.com\n    Port 443\n    User git\n'
       f'    ProxyCommand "{Path(sys.executable).with_name("python.exe").as_posix()}" "{connector.as_posix()}" %h %p\nHost *\n'+end)
config.write_text(block+original,encoding='utf-8')
report={'time':time.time(),'https_scoped_keys':len(keys),'proxy':proxy,'ssh_host':'ssh.github.com','ssh_port':443,
        'ssh_proxy_command_installed':True,'global_unscoped_http_proxy_changed':False}
atomic_json(root/'runtime/github-configuration.json',report)
print(json.dumps(report))
