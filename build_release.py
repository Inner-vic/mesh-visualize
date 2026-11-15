"""Build a self-contained source/VSIX release without Node/npm or machine config."""
import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FILES=['view_camera.py','five_view.py','scene_visualize.py','mesh_visualize.py','generate.cmd','SKILL.md','mesh_eval.py','report-template.html','fixed10-scenes.json','VERSION',
       'requirements.txt','setup.py','setup.cmd','mesh.cmd','demo.cmd','install-plugin.cmd',
       'install_plugin.py','identity.example.json','mesh-evaluation.code-workspace',
       'README.md','AGENTS.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def zip_folder(folder, target, prefix=''):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():z.write(p, prefix+p.relative_to(folder).as_posix())
    with zipfile.ZipFile(target) as z:
        if z.testzip():raise RuntimeError('ZIP CRC failure')

def main():
    a=argparse.ArgumentParser();a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mesh-release-') as temp:
        stage=Path(temp)/'mesh-evaluation-1.4.0';stage.mkdir()
        for name in FILES:shutil.copyfile(ROOT/name,stage/name)
        for name in ['docs','tests']:
            shutil.copytree(ROOT/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
        if (ROOT/'wheels').exists():shutil.copytree(ROOT/'wheels',stage/'wheels')
        extension=Path(temp)/'vsix';extension.mkdir()
        shutil.copytree(ROOT/'vendor/gaussianformer-vis',extension/'extension')
        runtime=extension/'extension/runtime';runtime.mkdir()
        for name in ['mesh_eval.py','mesh_visualize.py','scene_visualize.py','five_view.py','view_camera.py','report-template.html','fixed10-scenes.json']:
            shutil.copyfile(ROOT/name,runtime/name)
        (extension/'extension/PROJECT_CHANGES.md').write_text((ROOT/'CHANGELOG.md').read_text(encoding='utf-8'),encoding='utf-8')
        (extension/'[Content_Types].xml').write_text('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="json" ContentType="application/json"/><Default Extension="js" ContentType="application/javascript"/><Default Extension="py" ContentType="text/plain"/><Default Extension="html" ContentType="text/html"/><Default Extension="css" ContentType="text/css"/><Default Extension="md" ContentType="text/markdown"/><Default Extension="vsixmanifest" ContentType="text/xml"/></Types>',encoding='utf-8')
        (extension/'extension.vsixmanifest').write_text("""<?xml version="1.0" encoding="utf-8"?><PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011"><Metadata><Identity Language="en-US" Id="gaussianformer-vis" Version="1.0.25" Publisher="gaussianformer"/><DisplayName>GaussianFormer Visualizer (Mesh Project)</DisplayName><Description xml:space="preserve">Project package of the supplied visualizer with fixed-ten review entry.</Description><Tags>Visualization</Tags><Categories>Visualization</Categories><Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.74.0"/><Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/></Properties></Metadata><Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation><Dependencies/><Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets></PackageManifest>""",encoding='utf-8')
        (stage/'plugins').mkdir()
        vsix=stage/'plugins/gaussianformer-vis-1.0.25.vsix'
        zip_folder(extension,vsix)
        (stage/'plugin-source').mkdir()
        shutil.copytree(extension/'extension',stage/'plugin-source/gaussianformer-vis')
        records={p.relative_to(stage).as_posix():sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage/'MANIFEST.sha256.json').write_text(json.dumps({'version':'1.4.0','files':records},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        archive=args.out/'mesh-evaluation-1.4.0.zip'
        zip_folder(stage,archive,'mesh-evaluation-1.4.0/')
        checksums=args.out/'mesh-evaluation-1.4.0.sha256.txt'
        checksums.write_text(sha(archive)+'  '+archive.name+'\n',encoding='utf-8')
        print(json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'files':len(records),
                          'sha256':sha(archive),'vsix_version':'1.0.25'},ensure_ascii=False))
if __name__=='__main__':main()
