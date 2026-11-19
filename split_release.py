"""Prepare verified release parts for GitLab's 10 MiB web attachment limit."""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def prepare_uploads(archive, expected_sha256):
    archive = Path(archive)
    rows, digest = [], hashlib.sha256()
    with archive.open('rb') as stream:
        index = 1
        for block in iter(lambda: stream.read(9 * 1024 * 1024), b''):
            path = archive.with_name(archive.name + '.' + str(index).zfill(3))
            with path.open('xb') as target:
                target.write(block)
            digest.update(block)
            rows.append({'filename': path.name, 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
            index += 1
    if digest.hexdigest() != expected_sha256:
        raise ValueError('Archive changed during splitting')
    script = archive.with_name('restore-' + archive.stem + '.py')
    text = '''"""Restore the release ZIP from verified parts; requires only Python standard library."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = __PARTS__
FILENAME = __FILENAME__
EXPECTED = __SHA256__

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    target = ROOT / FILENAME
    if target.exists():
        if sha(target) == EXPECTED:
            print('Verified existing ZIP: ' + str(target))
            return
        raise ValueError('A different ZIP already exists; use an empty directory')
    for row in PARTS:
        path = ROOT / row['filename']
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Missing, incomplete or modified part: ' + row['filename'])
    created = False
    try:
        with target.open('xb') as output:
            created = True
            for row in PARTS:
                with (ROOT / row['filename']).open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        output.write(chunk)
        if sha(target) != EXPECTED:
            raise ValueError('Restored ZIP checksum mismatch')
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise
    print('Verified and restored ZIP: ' + str(target))

if __name__ == '__main__':
    main()
'''
    text = text.replace('__PARTS__', repr(rows)).replace('__FILENAME__', repr(archive.name)).replace('__SHA256__', repr(expected_sha256))
    script.write_text(text, encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='mesh-restore-check-') as temporary:
        destination = Path(temporary)
        for name in [row['filename'] for row in rows] + [script.name]:
            shutil.copyfile(archive.parent / name, destination / name)
        subprocess.run([sys.executable, str(destination / script.name)], check=True)
    return {'restore_script': script.name, 'parts': rows, 'restoration_executed': True}
