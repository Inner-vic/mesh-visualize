"""Maintainer-side verification and Windows offline packaging, without GitLab CI."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from split_release import prepare_uploads

ROOT = Path(__file__).resolve().parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if not (destination / item.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError('Archive entry escapes destination')
        if bundle.testzip() is not None:
            raise ValueError('Archive CRC mismatch')
        bundle.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    parser.add_argument('--offline', action='store_true', help='Use already prepared wheels; do not download')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new or empty output directory to preserve existing releases')
    out.mkdir(parents=True, exist_ok=True)
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    receipt = out / ('mesh-evaluation-' + version + '.checks.json')
    if receipt.exists():
        raise ValueError('Verification receipt already exists; use a fresh output directory')
    checks = []
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')

    def run(command, name, cwd=ROOT, capture=False):
        print('Checking: ' + name, flush=True)
        result = subprocess.run(command, cwd=cwd, env=env, check=True,
                                capture_output=capture, text=True, encoding='utf-8' if capture else None)
        checks.append({'name': name, 'status': 'passed'})
        return result

    catalog = json.loads((ROOT / 'SOURCE-MANIFEST.json').read_text(encoding='utf-8'))
    for name, expected in catalog['files'].items():
        if sha(ROOT / name) != expected:
            raise ValueError('Source manifest mismatch: ' + name)
    checks.append({'name': 'source_manifest', 'status': 'passed', 'files': len(catalog['files'])})
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 'unit_tests')
    node = shutil.which('node')
    if not node:
        raise ValueError('Maintainer verification requires Node.js for plugin syntax checks')
    for name in ['extension.js', 'media/panel.js']:
        run([node, '--check', str(ROOT / 'vendor/gaussianformer-vis' / name)], 'plugin_syntax:' + name)
    wheels = ROOT / 'wheels'
    if not args.offline:
        run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--platform', 'win_amd64',
             '--python-version', '312', '--implementation', 'cp', '--abi', 'cp312',
             '-r', str(ROOT / 'requirements.txt'), '--dest', str(wheels)], 'windows_wheels')
    required = []
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.]+)', line.strip())
        if not match:
            raise ValueError('Offline packaging requires exact dependency pins')
        name, pinned = match.groups()
        prefix = name.replace('-', '_').lower() + '-' + pinned + '-'
        matches = [path for path in wheels.glob('*.whl') if path.name.lower().startswith(prefix)
                   and path.name.lower().endswith('-cp312-cp312-win_amd64.whl')]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous Windows wheel: ' + name)
        required.append(matches[0])
    if {path.name for path in required} != {path.name for path in wheels.iterdir()}:
        raise ValueError('Unexpected files in wheels; keep only the pinned Windows dependencies')
    run([sys.executable, str(ROOT / 'build_release.py'), '--out', str(out)], 'build_release')
    archive = out / ('mesh-evaluation-' + version + '.zip')
    fresh_install = False
    with tempfile.TemporaryDirectory(prefix='mesh-local-release-') as temp:
        destination = Path(temp)
        verify_archive(archive, destination)
        package = destination / ('mesh-evaluation-' + version)
        manifest = json.loads((package / 'MANIFEST.sha256.json').read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            if sha(package / name) != expected:
                raise ValueError('Package manifest mismatch: ' + name)
        checks.append({'name': 'package_crc_and_manifest', 'status': 'passed', 'files': len(manifest['files'])})
        for path in (package / 'plugins').glob('*.vsix'):
            with zipfile.ZipFile(path) as bundle:
                if bundle.testzip() is not None:
                    raise ValueError('VSIX CRC mismatch')
        checks.append({'name': 'vsix_crc', 'status': 'passed'})
        for path in (package / 'wheels').glob('*.whl'):
            with zipfile.ZipFile(path) as bundle:
                if bundle.testzip() is not None:
                    raise ValueError('Wheel CRC mismatch')
        inputs = package / 'outputs/demo-inputs'
        verify_archive(package / 'docs/examples/pointcloud-inputs.zip', inputs)
        prepared = inputs / 'pointcloud-demo-inputs'
        provenance = json.loads((prepared / 'preview-provenance.json').read_text(encoding='utf-8'))
        input_count = 0
        for record in provenance['records']:
            for name, detail in record['files'].items():
                if sha(prepared / 'vis' / name) != detail['prepared_sha256']:
                    raise ValueError('Demo input mismatch: ' + name)
                input_count += 1
        checks.append({'name': 'real_demo_input_hashes', 'status': 'passed', 'files': input_count})
        render_python = sys.executable
        if os.name == 'nt' and sys.version_info[:2] == (3, 12):
            run([sys.executable, str(package / 'setup.py'), '--offline'], 'fresh_offline_dependency_install', cwd=package)
            render_python = str(package / '.venv/Scripts/python.exe')
            fresh_install = True
        result = run([render_python, str(package / 'pointcloud_visualize.py'), '--vis', str(prepared / 'vis'),
                      '--out', str(package / 'outputs/pointcloud-demo')], 'extracted_package_real_demo', capture=True)
        output = json.loads(result.stdout)
        images = output['artifacts']['primary_images']
        if output['selection'] != ['0', '40', '80'] or len(images) != 3:
            raise ValueError('Unexpected demo selection')
        for row in images:
            if sha(Path(row['path'])) != row['sha256']:
                raise ValueError('Demo output hash mismatch')
        checks.append({'name': 'real_demo_output_hashes', 'status': 'passed', 'images': len(images)})
    archive_hash = sha(archive)
    checksum = out / ('mesh-evaluation-' + version + '.sha256.txt')
    if checksum.read_text(encoding='utf-8').split()[0] != archive_hash:
        raise ValueError('Release checksum mismatch')
    upload_files = prepare_uploads(archive, archive_hash)
    checks.append({'name': 'upload_parts_restoration', 'status': 'passed', 'parts': len(upload_files['parts'])})
    report = {'schema': 'mesh-visualize.local-release-checks/v1', 'status': 'passed', 'version': version,
              'platform': platform.system(), 'python': platform.python_version(),
              'source_manifest_sha256': sha(ROOT / 'SOURCE-MANIFEST.json'),
              'archive': {'filename': archive.name, 'bytes': archive.stat().st_size, 'sha256': archive_hash},
              'checks': checks, 'upload_files': upload_files, 'ci_used': False, 'model_training_or_inference_performed': False,
              'fresh_dependency_install_verified_by_this_call': fresh_install,
              'images_visually_inspected_by_this_call': False}
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'archive': str(archive), 'checks': str(receipt)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
