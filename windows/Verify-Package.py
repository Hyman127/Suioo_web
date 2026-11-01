"""Check a release ZIP and all declared hashes without extracting or running it."""
import argparse
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import sys
import time
import zipfile
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('archive',nargs='?');args=parser.parse_args()
path=Path(args.archive) if args.archive else max(root.glob('Suioo_web_*.zip'),key=lambda p:p.stat().st_mtime)
errors=[]
with zipfile.ZipFile(path) as archive:
    names=archive.namelist()
    for name in names:
        parts=PurePosixPath(name).parts
        if not parts or parts[0]!='Suioo_web' or '..' in parts or 'data' in parts or '__pycache__' in parts:
            errors.append('Unsafe or private archive member: '+name)
        if len(parts)>1 and parts[1]=='runtime' and parts[2:3]!=('engine',):errors.append('Private runtime member: '+name)
        if parts[-1]=='config.json':errors.append('Runtime configuration included')
    manifest=json.loads(archive.read('Suioo_web/MANIFEST.json'))
    expected={'Suioo_web/'+row['path'] for row in manifest['files']}|{'Suioo_web/MANIFEST.json','Suioo_web/SHA256SUMS'}
    if set(names)!=expected or len(names)!=len(expected):errors.append('Manifest membership mismatch')
    for row in manifest['files']:
        body=archive.read('Suioo_web/'+row['path'])
        if len(body)!=row['bytes'] or hashlib.sha256(body).hexdigest()!=row['sha256']:errors.append('Hash mismatch: '+row['path'])
        if row['path'].endswith('.py'):ast.parse(body.decode('utf-8-sig'),filename=row['path'])
        elif row['path'].endswith('.json'):json.loads(body.decode('utf-8-sig'))
report={'time':time.time(),'passed':not errors,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'entries':len(names),'declared_files':len(manifest['files']),'errors':errors}
(root/'runtime/package-verification-20261101.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
sys.exit(0 if report['passed'] else 1)
