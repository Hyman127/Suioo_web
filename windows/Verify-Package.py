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
    allowed=set(json.loads(archive.read('Suioo_web/publish-files.json'))['files'])
    sys.path.insert(0,str(root))
    from bootstrap import ENGINE_ARCHIVE,ENGINE_SHA256
    bundled='vendor/'+ENGINE_ARCHIVE
    declared={row['path'] for row in manifest['files']}
    codex_release=json.loads(archive.read('Suioo_web/windows/codex-release.json'))
    if codex_release!=json.loads((root/'windows/codex-release.json').read_text(encoding='utf-8')):
        errors.append('Codex release pin differs from verifier')
    codex_bundled='vendor/'+codex_release['archive']
    optional={bundled,codex_bundled}
    if declared-optional!=allowed or declared-allowed-optional:errors.append('Archive differs from public file allowlist')
    if bool(manifest.get('engine_bundled'))!=(bundled in declared):errors.append('Engine bundle flag mismatch')
    if bool(manifest.get('codex_bundled'))!=(codex_bundled in declared):errors.append('Codex bundle flag mismatch')
    if codex_bundled in declared and hashlib.sha256(archive.read('Suioo_web/'+codex_bundled)).hexdigest()!=codex_release['sha256']:
        errors.append('Bundled Codex checksum mismatch')
    if bundled in declared and hashlib.sha256(archive.read('Suioo_web/'+bundled)).hexdigest()!=ENGINE_SHA256:
        errors.append('Bundled engine checksum mismatch')
    expected={'Suioo_web/'+row['path'] for row in manifest['files']}|{'Suioo_web/MANIFEST.json','Suioo_web/SHA256SUMS'}
    if set(names)!=expected or len(names)!=len(expected):errors.append('Manifest membership mismatch')
    for row in manifest['files']:
        body=archive.read('Suioo_web/'+row['path'])
        if len(body)!=row['bytes'] or hashlib.sha256(body).hexdigest()!=row['sha256']:errors.append('Hash mismatch: '+row['path'])
        if row['path'].endswith('.py'):ast.parse(body.decode('utf-8-sig'),filename=row['path'])
        elif row['path'].endswith('.json'):json.loads(body.decode('utf-8-sig'))
    checksums=''.join(row['sha256']+'  '+row['path']+'\n' for row in manifest['files']).encode('utf-8')
    if archive.read('Suioo_web/SHA256SUMS')!=checksums:errors.append('SHA256SUMS mismatch')
report={'time':time.time(),'passed':not errors,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'entries':len(names),'declared_files':len(manifest['files']),'errors':errors}
(root/'runtime').mkdir(exist_ok=True)
(root/'runtime/package-verification-20261101.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
sys.exit(0 if report['passed'] else 1)
