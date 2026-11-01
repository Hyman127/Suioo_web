"""Create a reviewable development package without credentials, logs or browser profiles."""
import hashlib
import json
import time
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = []
for path in root.rglob('*'):
    if not path.is_file():
        continue
    relative = path.relative_to(root)
    if set(relative.parts) & {'data','__pycache__'} or path.suffix in ('.zip','.pyc','.tmp'):
        continue
    if relative.parts[0] == 'runtime' and relative.parts[:2] != ('runtime','engine'):
        continue
    if path.name in ('config.json','MANIFEST.json','SHA256SUMS'):
        continue
    files.append(path)
files.sort()
rows = [{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,
         'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
manifest = root/'MANIFEST.json'
manifest.write_text(json.dumps({'created':time.time(),'files':rows,
                    'excludes':['data','config.json','runtime logs/history/browser profiles'],
                    'python':'Python 3.12 required; existing host interpreter or runtime/python'},
                    ensure_ascii=False,indent=2),encoding='utf-8')
checksums = root/'SHA256SUMS'
checksums.write_text(''.join(r['sha256']+'  '+r['path']+'\n' for r in rows),encoding='utf-8')
output = root/('Suioo_web_' + time.strftime('%Y%m%d') + '.zip')
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as archive:
    for p in files+[manifest,checksums]:
        archive.write(p,'Suioo_web/'+p.relative_to(root).as_posix())
print(json.dumps({'file':str(output),'bytes':output.stat().st_size,
                  'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'entries':len(files)+2}))
