import argparse
import shutil
import subprocess
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--editor', choices=['code','cursor'], default=None)
a=p.parse_args()
editor=a.editor or next((name for name in ['cursor','code'] if shutil.which(name)), None)
if not editor or not shutil.which(editor):
    raise SystemExit('Editor CLI unavailable. In VS Code/Cursor choose Extensions > Install from VSIX and select plugins/*.vsix.')
vsix=Path(__file__).resolve().parent/'plugins/gaussianformer-vis-1.0.25.vsix'
if not vsix.is_file():raise SystemExit('VSIX missing; use the release ZIP.')
subprocess.run([shutil.which(editor), '--install-extension', str(vsix)], check=True)
