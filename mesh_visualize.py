"""Atomic project capability: completed Mesh vis -> 10 fixed-view five-pane figures plus diagnostics."""
import argparse
import contextlib
import hashlib
import io
import json
import tempfile
from pathlib import Path
import mesh_eval as core
import scene_visualize as scene
import five_view
from view_camera import settings as camera_settings

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def response(out, manifest, fingerprint, reused, manifest_sha256=None):
    images = [{key: row[key] for key in ['index','scene_name','frame_index']} |
              {kind: {'path':str(out / value['path']),'sha256':value['sha256']}
               for kind,value in row['images'].items()} for row in manifest['rows']]
    cards=[{'index':row['index'],'scene_name':row['scene_name'],
            'path':str(out/row['scene_card']['path']),'sha256':row['scene_card']['sha256']}
           for row in manifest['rows'] if 'scene_card' in row]
    return {'schema':'mesh-visualize.result/v1','capability':'mesh-visualize',
            'version':core.VERSION,'status':'generated','reused':reused,
            'request_fingerprint':fingerprint,'identity_bound':not manifest.get('generation_only'),
            'display_camera':manifest.get('display_camera'),'review_performed_by_this_call':False,'model_quality_verdict':None,
            'run_manifest_sha256':manifest_sha256 or core.digest(out/'run-manifest.json'),
            'artifacts':{'report':str(out/'index.html'),'manifest':str(out/'run-manifest.json'),
                         'review_template':str(out/'review-template.json'),
                         'primary_view':manifest.get('primary_view','diagnostic'),
                         'scene_card_count':len(cards),'five_view_count':len(cards) if manifest.get('primary_view')=='viewer' else 0,'primary_images':cards,
                         'comparison_count':10,'difference_count':10,'samples':images}}

def generate(vis_dir, output_dir, identity=None, view="viewer", elevation_deg=30., azimuth_deg=8.):
    """Return JSON-compatible artifact references; no browser, model, or platform calls.

    identity is optional actual task/checkpoint/code metadata. Its absence permits
    image generation, marks the output unbound, and disallows formal finalization.
    Existing identical outputs are verified/reused. Different inputs never overwrite.
    """
    if view not in ['viewer','scene','diagnostic']:
        raise ValueError('view must be viewer, scene or diagnostic')
    if identity is not None and not isinstance(identity,dict):
        raise ValueError('identity must be an object or null')
    camera=camera_settings(elevation_deg,azimuth_deg)
    identity = identity if identity is not None else {}
    if identity:
        core.identity_check(identity)
    vis,out=Path(vis_dir).resolve(),Path(output_dir).resolve()
    protocol_path=core.ROOT/'fixed10-scenes.json'
    pairs,_=core.inspect_vis(vis,core.load(protocol_path))
    frozen_inputs=[{'scene_name':pair['scene_name'],
                    'files':{key:core.digest(path) for key,path in pair['files'].items()}}
                   for pair in pairs]
    context=[]
    renderer=five_view if view=='viewer' else scene
    if view in ['viewer','scene']:
        for pair in pairs:
            files=renderer.context_files(vis,pair['source_index'])
            context.append({key:core.digest(path) for key,path in files.items()})
    fingerprint=canonical_sha({'display_camera':camera,'view':view,'context':context,'version':core.VERSION,'protocol_sha256':core.digest(protocol_path),
                              'identity':identity,'inputs':frozen_inputs})
    if out.exists() and not out.is_dir():
        raise ValueError('Output path is not a directory')
    if out.exists() and any(out.iterdir()):
        prior=core.load(out/'capability-result.json')
        manifest=core.checked_manifest(out)
        if (prior.get('request_fingerprint')!=fingerprint
                or prior.get('run_manifest_sha256')!=core.digest(out/'run-manifest.json')):
            raise ValueError('Output belongs to different inputs or changed evidence; choose a new directory')
        return response(out,manifest,fingerprint,True)
    out.parent.mkdir(parents=True,exist_ok=True)
    # Publish only after all twenty files and identities have passed verification.
    with tempfile.TemporaryDirectory(prefix='.mesh-generation-',dir=out.parent) as tmp:
        stage=Path(tmp)/'output'
        with contextlib.redirect_stdout(io.StringIO()):
            core.render(vis,stage,identity,protocol_path,generation_only=not bool(identity))
        manifest=core.checked_manifest(stage)
        if view in ['viewer','scene']:
            for index,pair in enumerate(pairs):
                relative=f'five-views/{index}_viewer.png' if view=='viewer' else f'scene-views/{index}_scene.png'
                card=renderer.make_card(vis,pair['source_index'],stage/relative,index=index,
                                        elevation_deg=camera['elevation_deg'],azimuth_deg=camera['azimuth_deg'])
                if {key:value['sha256'] for key,value in card['sources'].items()} != context[index]:
                    raise ValueError('Scene context changed during rendering; output not published')
                card['path']=relative
                manifest['rows'][index]['scene_card']=card
            manifest['display_camera']=camera
            manifest['primary_view']=view
            manifest['scene_view_profile']='five-view/v1' if view=='viewer' else 'camera-mesh-card/v1'
            core.dump(stage/'run-manifest.json',manifest)
            review=core.load(stage/'review-template.json')
            review['run_manifest_sha256']=core.digest(stage/'run-manifest.json')
            for original,row in zip(manifest['rows'],review['rows']):
                row['scene_card']=original['scene_card']
            core.dump(stage/'review-template.json',review)
            core.report(stage,manifest,review)
            core.checked_manifest(stage)
        if [{key:row[key] for key in ['scene_name']} |
            {'files':row['input_sha256']} for row in manifest['rows']] != frozen_inputs:
            raise ValueError('Input files changed during rendering; output not published')
        result=response(out,manifest,fingerprint,False,core.digest(stage/'run-manifest.json'))
        core.dump(stage/'capability-result.json',result)
        if out.exists():out.rmdir()  # Only remove a verified empty destination.
        stage.rename(out)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vis',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--view',choices=['viewer','scene','diagnostic'],default='viewer')
    p.add_argument('--elevation-deg',type=float,default=30.,help='0=horizontal, 90=top-down; default 30')
    p.add_argument('--azimuth-deg',type=float,default=8.,help='0 looks along vehicle +X; default 8')
    p.add_argument('--identity',type=Path,help='Optional actual evaluation identity JSON')
    args=p.parse_args()
    try:
        result=generate(args.vis,args.out,core.load(args.identity) if args.identity else None,view=args.view,elevation_deg=args.elevation_deg,azimuth_deg=args.azimuth_deg)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError,ImportError) as exc:
        print(json.dumps({'schema':'mesh-visualize.result/v1','capability':'mesh-visualize',
                          'status':'failed','error':str(exc)},ensure_ascii=False))
        return 2

if __name__=='__main__':raise SystemExit(main())
