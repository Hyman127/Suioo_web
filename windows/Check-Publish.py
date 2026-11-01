"""Inspect only Git index blobs. Never print local credentials or secret matches."""
import base64
import json
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
PUBLIC_DOCS={'docs/首次使用与凭据保存.txt','docs/第三方组件.txt'}
PATTERNS=[rb'gh[pousr]_[A-Za-z0-9]{20,}',rb'github_pat_[A-Za-z0-9_]{20,}',
          rb'sk-[A-Za-z0-9_-]{32,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']

def git(root,*args,**kwargs):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,**kwargs)
    if result.returncode:raise RuntimeError('Git index could not be inspected')
    return result.stdout

def inspect_index(root,known_credentials=()):
    root=Path(root);allowed=set(json.loads((root/'publish-files.json').read_text(encoding='utf-8'))['files'])
    entries=[];errors=[]
    for record in git(root,'ls-files','--stage','-z').split(b'\0'):
        if not record:continue
        header,path=record.split(b'\t',1);mode,oid,stage=header.split();name=path.decode('utf-8')
        parts=PurePosixPath(name).parts
        forbidden=(not parts or '..' in parts or parts[0] in {'runtime','data','evidence','.ssh','.codex','.git'} or
                   name=='config.json' or name.endswith(('.dpapi','.zip','.pem','.key','.pfx','.p12','.sqlite3','.log')) or
                   (name.startswith('docs/') and name not in PUBLIC_DOCS))
        if forbidden or name not in allowed:errors.append({'path':name,'reason':'private or unapproved path'})
        if mode not in (b'100644',b'100755') or stage!=b'0':errors.append({'path':name,'reason':'unsupported index mode or conflict'})
        entries.append((name,oid))
    if not entries:errors.append({'path':'','reason':'empty publication index'})
    payload=git(root,'cat-file','--batch',input=b'\n'.join(oid for _,oid in entries)+b'\n') if entries else b''
    offset=0
    values=[]
    for value in known_credentials:
        if not value:continue
        values.extend([str(value).encode('utf-8'),str(value).encode('utf-16le'),quote(str(value),safe='').encode('ascii')])
    for name,_ in entries:
        end=payload.index(b'\n',offset);header=payload[offset:end].split();length=int(header[2]);body=payload[end+1:end+1+length];offset=end+length+2
        if length>4*1024*1024:errors.append({'path':name,'reason':'unexpectedly large publication file'})
        if any(value in body for value in values):errors.append({'path':name,'reason':'saved credential detected'})
        if any(re.search(pattern,body) for pattern in PATTERNS):errors.append({'path':name,'reason':'token or private-key material detected'})
    return {'passed':not errors,'indexed_files':len(entries),'errors':errors}

def main():
    credentials=[]
    if (ROOT/'data/connection.dpapi').exists():
        sys.path.insert(0,str(ROOT));import vault
        values=vault.load();credentials=[values.get('username',''),values.get('password','')]
        if all(credentials):credentials.append(base64.b64encode((credentials[0]+':'+credentials[1]).encode()).decode())
    result=inspect_index(ROOT,credentials)
    (ROOT/'runtime').mkdir(exist_ok=True)
    (ROOT/'runtime/publish-scan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result));return 0 if result['passed'] else 1

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print('Publication check failed; index or local credentials could not be safely inspected.',file=sys.stderr)
        sys.exit(1)
