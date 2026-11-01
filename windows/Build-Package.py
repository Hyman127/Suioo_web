"""Build a clean migration ZIP from the explicit public file list."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
import zipfile


def build(root, output_dir, include_engine=False, include_codex=False):
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    names = json.loads((root / 'publish-files.json').read_text(encoding='utf-8'))['files']
    if len(names) != len(set(names)):
        raise ValueError('Duplicate publication paths')
    payload = {}
    for name in names:
        parts = PurePosixPath(name).parts
        if (not parts or PurePosixPath(name).is_absolute() or '\\' in name or ':' in name or
                any(p in {'.', '..', '.git', '.codex', '.ssh', 'data', 'runtime', 'evidence'} for p in parts) or
                name.endswith(('.dpapi', '.zip', '.pem', '.key', '.log')) or name == 'config.json'):
            raise ValueError('Unsafe publication path: ' + name)
        path = root / name
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p.is_relative_to(root)):
            raise ValueError('Publication path contains a link: ' + name)
        payload[name] = path.read_bytes()
    if include_engine:
        import sys
        sys.path.insert(0, str(root))
        from bootstrap import ENGINE_ARCHIVE, ENGINE_SHA256
        body = (root / 'vendor' / ENGINE_ARCHIVE).read_bytes()
        if hashlib.sha256(body).hexdigest() != ENGINE_SHA256:
            raise ValueError('Engine archive checksum mismatch')
        payload['vendor/' + ENGINE_ARCHIVE] = body
    if include_codex:
        release = json.loads((root / 'windows/codex-release.json').read_text(encoding='utf-8'))
        body = (root / 'vendor' / release['archive']).read_bytes()
        if hashlib.sha256(body).hexdigest() != release['sha256']:
            raise ValueError('Codex archive checksum mismatch')
        payload['vendor/' + release['archive']] = body
    rows = [{'path': name, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
            for name, body in sorted(payload.items())]
    payload['MANIFEST.json'] = json.dumps({'created': time.time(), 'files': rows,
        'excludes': ['Git history', 'credentials', 'machine configuration', 'runtime history', 'UAT evidence'],
        'python': 'Python 3.12 or newer required', 'engine_bundled': include_engine,
        'codex_bundled': include_codex},
        ensure_ascii=False, indent=2).encode('utf-8')
    payload['SHA256SUMS'] = ''.join(row['sha256'] + '  ' + row['path'] + '\n' for row in rows).encode('utf-8')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ('Suioo_web_' + time.strftime('%Y%m%d_%H%M%S') + '.zip')
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for name, body in sorted(payload.items()):
            archive.writestr('Suioo_web/' + name, body)
    return {'file': str(output), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'entries': len(payload)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--include-engine', action='store_true')
    parser.add_argument('--include-codex', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(build(root, args.output_dir or root, args.include_engine, args.include_codex), ensure_ascii=False))
