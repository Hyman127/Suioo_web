"""Install the pinned, bundled public engine on a clean Windows checkout."""
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent
ENGINE_ARCHIVE='sing-box-1.14.4-windows-amd64.zip'
ENGINE_SHA256='99185d75d314a07dbba4a130c8ad986cbeb629a07927975636b341ca61f991df'
ENGINE_FILES=('sing-box.exe','libcronet.dll','LICENSE')
ENGINE_URL='https://github.com/SagerNet/sing-box/releases/download/v1.14.4/'+ENGINE_ARCHIVE

def download_engine(target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.download')
    try:
        request=urllib.request.Request(ENGINE_URL,headers={'User-Agent':'Suioo-Web-Bootstrap/1.0'})
        print('First launch: downloading the official proxy engine; no account is sent.')
        digest=hashlib.sha256();size=0
        with urllib.request.urlopen(request,timeout=30) as response,temporary.open('wb') as stream:
            while content:=response.read(1024*1024):
                size+=len(content)
                if size>256*1024*1024:raise RuntimeError('Engine download exceeds expected size')
                digest.update(content);stream.write(content)
        if digest.hexdigest()!=ENGINE_SHA256:raise RuntimeError('Engine download checksum mismatch')
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)

def ensure_engine(root=ROOT):
    root=Path(root);destination=root/'runtime'/'engine'
    if all((destination/name).is_file() for name in ENGINE_FILES):return False
    source=root/'vendor'/ENGINE_ARCHIVE
    if not source.is_file():download_engine(source)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=ENGINE_SHA256:
        raise RuntimeError('Bundled engine checksum mismatch; no files were installed')
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for name in ENGINE_FILES:
            target=destination/name
            if target.exists():continue  # Never overwrite a running installation.
            content=archive.read('sing-box-1.14.4-windows-amd64/'+name)
            with tempfile.NamedTemporaryFile(dir=destination,delete=False,suffix='.install') as temporary:
                temporary.write(content);path=Path(temporary.name)
            try:os.replace(path,target)
            finally:path.unlink(missing_ok=True)
    return True
