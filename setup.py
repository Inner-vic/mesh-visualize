"""Create a package-local venv; install pinned postprocessing dependencies."""
import os
import subprocess
import sys
import venv
from pathlib import Path

root = Path(__file__).resolve().parent
if not (3,10) <= sys.version_info[:2] <= (3,13):
    raise SystemExit('Python 3.10 through 3.13 required; Windows offline package supports Python 3.12 x64.')
target = root / '.venv'
venv.EnvBuilder(with_pip=True).create(target)
python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
args = [str(python), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')]
offline_default = os.name == 'nt' and sys.version_info[:2] == (3,12) and (root / 'wheels').is_dir()
if '--offline' in sys.argv or (offline_default and '--online' not in sys.argv):
    args += ['--no-index', '--find-links', str(root / 'wheels')]
subprocess.run(args, check=True)
subprocess.run([str(python), str(root / 'mesh_eval.py'), 'doctor'], check=True)
print('Ready. Run demo.cmd on Windows, or .venv/bin/python mesh_eval.py demo --out outputs/demo --open')
