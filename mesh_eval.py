#!/usr/bin/env python3
"""Project-specific, offline postprocessing of completed 2.5D Mesh evaluations."""
import argparse
import datetime as dt
import hashlib
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = '1.5.1'
LABELS = {1: '沥青', 2: '水泥', 4: '砖石路', 16: '减速带', 17: '井盖',
          23: '桥梁接缝', 24: '可移动障碍物', 25: '不可移动障碍物'}
COLORS = {1: (127,127,127), 2: (200,200,200), 4: (160,120,70), 16: (255,0,0),
          17: (0,128,255), 23: (255,165,0), 24: (0,200,0), 25: (128,0,200)}
JUDGMENTS = ['classification', 'boundary', 'shape', 'matching']

def fail(message):
    raise ValueError(message)

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      parse_constant=lambda x: fail('JSON contains nonfinite value: ' + x))

def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def np_array(path, columns):
    import numpy as np
    array = np.load(path, allow_pickle=False)
    if (array.ndim != 2 or array.shape[1] != columns or not len(array)
            or not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all()):
        fail('Invalid numeric array: ' + str(path))
    labels = array[:,3]
    if not np.equal(labels, np.floor(labels)).all() or labels.min() < 0 or labels.max() > 26:
        fail('Invalid class IDs: ' + str(path))
    return array

def inspect_vis(vis, protocol):
    import numpy as np
    vis = Path(vis).resolve()
    expected = protocol['scene_order']
    if len(expected) != 10 or len(set(expected)) != 10:
        fail('Protocol must have exactly 10 distinct scenes')
    if hashlib.sha256('\n'.join(expected).encode()).hexdigest() != protocol['scene_order_sha256']:
        fail('Protocol scene order hash mismatch')
    if protocol['frames'] != [7] * 10 or set(protocol['source_gt_hashes']) != set(expected):
        fail('Protocol frame/GT manifest incomplete')
    pairs = {}
    paths = sorted(vis.glob('*_paths.json'))
    if len(paths) != 10:
        fail('Expected exactly 10 *_paths.json files')
    counts = {str(k): 0 for k in LABELS}
    for meta_path in paths:
        base = meta_path.name[:-len('_paths.json')]
        if not re.fullmatch(r'\d+', base):
            fail('Expected numeric sample filenames: ' + base)
        meta = load(meta_path)
        scene = meta.get('scene_name')
        if scene not in expected or scene in pairs or meta.get('datalink_frame', {}).get('frame_index') != 7:
            fail('Unexpected/duplicate scene or wrong frame: ' + str(scene))
        files = {'gt': vis / (base + '_gt.pcd.bin.npy'),
                 'pred': vis / (base + '_pred.pcd.bin.npy'),
                 'mesh_gt': vis / (base + '_mesh_gt.npy'), 'metadata': meta_path}
        if not all(p.is_file() for p in files.values()):
            fail('Missing GT/PRED/mesh GT/metadata for sample ' + base)
        if digest(files['mesh_gt']) != protocol['source_gt_hashes'][scene]:
            fail('Source mesh GT hash mismatch: ' + scene)
        gt, pred = np_array(files['gt'], 4), np_array(files['pred'], 4)
        mesh = np_array(files['mesh_gt'], 5)
        for label in LABELS:
            counts[str(label)] += int((mesh[:,3] == label).sum())
        pairs[scene] = {'source_index': base, 'scene_name': scene, 'files': files}
    if set(pairs) != set(expected) or any(count == 0 for count in counts.values()):
        fail('Fixed scenes or eight-class GT coverage incomplete')
    # Reject unpaired extra point clouds instead of silently choosing ten.
    for suffix in ['_gt.pcd.bin.npy', '_pred.pcd.bin.npy', '_mesh_gt.npy']:
        if len(list(vis.glob('*' + suffix))) != 10:
            fail('Expected exactly 10 files ending ' + suffix)
    return [pairs[scene] for scene in expected], counts

def raster(points, bounds):
    import numpy as np
    lo_x, lo_y, hi_x, hi_y = bounds
    width = int(np.floor((hi_x - lo_x) / .1)) + 1
    height = int(np.floor((hi_y - lo_y) / .1)) + 1
    if width < 1 or height < 1 or width * height > 4_000_000:
        fail('BEV bounds exceed 4 million cells; check input units')
    x = np.clip(np.floor((points[:,0] - lo_x) / .1).astype(int), 0, width-1)
    y = np.clip(np.floor((points[:,1] - lo_y) / .1).astype(int), 0, height-1)
    # Stable mode; class-ID ascending is the declared tie break.
    keys, counts = np.unique((y * width + x) * 27 + points[:,3].astype(int), return_counts=True)
    cells, labels = keys // 27, keys % 27
    order = np.lexsort((labels, -counts, cells))
    cells, labels = cells[order], labels[order]
    first = np.r_[True, cells[1:] != cells[:-1]]
    grid = np.full(height * width, -1, dtype=int)
    grid[cells[first]] = labels[first]
    return np.flipud(grid.reshape(height, width))

def rgb(grid):
    import numpy as np
    picture = np.zeros((*grid.shape, 3), dtype=np.uint8)
    picture[grid >= 0] = (80,80,80)
    for label, color in COLORS.items():
        picture[grid == label] = color
    return picture

def identity_check(identity):
    for key in ['task_uid', 'checkpoint_sha256', 'code_commit', 'dataset_version']:
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            fail('Identity field required: ' + key)
    if not re.fullmatch('[0-9a-fA-F]{64}', identity['checkpoint_sha256']):
        fail('checkpoint_sha256 must be an actual 64-digit SHA256')
    if identity['dataset_version'] != '1.0.10':
        fail('This fixed protocol is bound to dataset 1.0.10')

def render(vis, out, identity, protocol_path, demo=False, generation_only=False):
    import numpy as np
    from PIL import Image
    protocol = load(protocol_path)
    if not demo:
        if not generation_only:
            identity_check(identity)
        if Path(protocol_path).resolve() != (ROOT / 'fixed10-scenes.json').resolve():
            fail('Production runs require this project fixed10 protocol')
    pairs, counts = inspect_vis(vis, protocol)
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        fail('Output directory must be new or empty: ' + str(out))
    out.mkdir(parents=True, exist_ok=True)
    image_dir = out / 'images'
    image_dir.mkdir()
    rows = []
    for index, pair in enumerate(pairs):
        gt, pred = np_array(pair['files']['gt'], 4), np_array(pair['files']['pred'], 4)
        bounds = [float(min(gt[:,0].min(), pred[:,0].min())), float(min(gt[:,1].min(), pred[:,1].min())),
                  float(max(gt[:,0].max(), pred[:,0].max())), float(max(gt[:,1].max(), pred[:,1].max()))]
        aligned = gt.shape == pred.shape and np.allclose(gt[:,:3], pred[:,:3], rtol=0, atol=1e-5)
        a, b = raster(gt, bounds), raster(pred, bounds)
        Image.fromarray(np.concatenate([rgb(a), rgb(b)], axis=1)).save(image_dir / f'{index}_gt_pred.png')
        occupied, different = (a >= 0) | (b >= 0), a != b
        diff = np.zeros((*a.shape, 3), dtype=np.uint8)
        diff[occupied & ~different] = (45,135,65)
        diff[different] = (255,60,90)
        Image.fromarray(diff).save(image_dir / f'{index}_diff.png')
        overlap = {}
        for label in LABELS:
            n_gt, n_pred, intersection = int((a == label).sum()), int((b == label).sum()), int(((a == label) & (b == label)).sum())
            overlap[str(label)] = {'gt_cells': n_gt, 'pred_cells': n_pred, 'intersection': intersection,
                                  'recall': intersection/n_gt if n_gt else None}
        rows.append({'index': index, 'source_index': pair['source_index'],
                     'scene_name': pair['scene_name'], 'frame_index': 7, 'bounds_xy': bounds,
                     'gt_point_count': len(gt), 'pred_point_count': len(pred),
                     'query_coordinates_aligned': bool(aligned),
                     'input_sha256': {key: digest(path) for key, path in pair['files'].items()},
                     'images': {key: {'path': f'images/{index}_{suffix}.png',
                                    'sha256': digest(image_dir / f'{index}_{suffix}.png')}
                                for key, suffix in [('comparison', 'gt_pred'), ('diff', 'diff')]},
                     'bev_diagnostic_not_formal_m1': overlap})
    shutil.copyfile(protocol_path, out / 'protocol.json')
    manifest = {'schema': 'mesh-m3-run/v1', 'tool_version': VERSION, 'created_at': utc(),
                'demo': demo, 'generation_only': generation_only, 'identity': identity, 'protocol_id': protocol['protocol_id'],
                'protocol_sha256': digest(out / 'protocol.json'), 'resolution_m': .1,
                'rendering': 'GT/PRED union XY bounds; independent rasterization; lowest class-ID breaks mode ties',
                'focus_gt_support': counts, 'rows': rows,
                'formal_m1': 'not_measured', 'm2': 'not_measured'}
    dump(out / 'run-manifest.json', manifest)
    review = {'schema': 'mesh-m3-review/v1', 'run_manifest_sha256': digest(out / 'run-manifest.json'),
              'reviewer': '', 'reviewer_type': 'human', 'completed_at': '',
              'overall_verdict': '', 'summary': '', 'read_evidence': [],
              'rows': [{**{k: row[k] for k in ['index', 'scene_name', 'frame_index']},
                        'images': row['images'], 'inspected': False,
                        **{key: '' for key in JUDGMENTS}, 'verdict': ''} for row in rows]}
    dump(out / 'review-template.json', review)
    report(out, manifest, review)
    print(json.dumps({'status': 'awaiting_visual_review', 'demo': demo,
                      'report': str(out / 'index.html'), 'images': 20}, ensure_ascii=False))
    return out

def checked_manifest(run):
    run = Path(run).resolve()
    manifest = load(run / 'run-manifest.json')
    if manifest.get('schema') != 'mesh-m3-run/v1' or [r['index'] for r in manifest['rows']] != list(range(10)):
        fail('Invalid run manifest or missing samples')
    if digest(run / 'protocol.json') != manifest['protocol_sha256']:
        fail('Protocol hash changed')
    protocol = load(run / 'protocol.json')
    if [r['scene_name'] for r in manifest['rows']] != protocol['scene_order']:
        fail('Scene identity mapping changed')
    if not manifest.get('demo'):
        if not manifest.get('generation_only'):
            identity_check(manifest['identity'])
        if manifest['protocol_sha256'] != digest(ROOT / 'fixed10-scenes.json'):
            fail('Production fixed protocol changed')
    expected = set()
    expected_cards=set()
    for row in manifest['rows']:
        if row['frame_index'] != 7 or set(row['images']) != {'comparison', 'diff'}:
            fail('Frame or image manifest incomplete')
        if 'scene_card' in row:
            card=row['scene_card'];target=run/card['path']
            if target.resolve().parent!=(run/('five-views' if manifest.get('primary_view')=='viewer' else 'scene-views')).resolve() or target.suffix!='.png':
                fail('Invalid scene-card path')
            if digest(target)!=card['sha256']:fail('Scene card hash mismatch')
            if card['scene_name']!=row['scene_name'] or card['source_index']!=row['source_index']:
                fail('Scene card identity mismatch')
            expected_cards.add(target.name)
        for key, image in row['images'].items():
            target = run / image['path']
            if target.resolve().parent != (run / 'images').resolve() or target.suffix != '.png':
                fail('Invalid image path')
            if digest(target) != image['sha256']:
                fail('Image hash mismatch: ' + image['path'])
            expected.add(target.name)
    if {p.name for p in (run / 'images').glob('*.png')} != expected or len(expected) != 20:
        fail('Expected exactly 20 distinct images')
    if manifest.get('primary_view') in ['viewer','scene']:
        if len(expected_cards)!=10 or {p.name for p in (run/('five-views' if manifest.get('primary_view')=='viewer' else 'scene-views')).glob('*.png')}!=expected_cards:
            fail('Expected exactly 10 scene cards')
    return manifest

def review_check(run, review):
    manifest = checked_manifest(run)
    if manifest.get('generation_only'):
        fail('Unbound generation output cannot finalize formal evaluation; generate a new identity-bound run first')
    if review.get('schema') != 'mesh-m3-review/v1' or review.get('run_manifest_sha256') != digest(Path(run) / 'run-manifest.json'):
        fail('Review is not bound to this exact run')
    for key in ['reviewer', 'completed_at', 'summary']:
        if not isinstance(review.get(key), str) or not review[key].strip():
            fail('Review field required: ' + key)
    try:
        timestamp = dt.datetime.fromisoformat(review['completed_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            fail('Review completion time requires timezone')
    except (ValueError, TypeError):
        fail('Invalid review completed_at timestamp')
    if review.get('reviewer_type') not in ['human', 'agent']:
        fail('reviewer_type must be human or agent')
    if review['reviewer_type'] == 'agent':
        evidence = review.get('read_evidence', [])
        wanted = ({(row['scene_card']['path'],row['scene_card']['sha256']) for row in manifest['rows']}
                  if manifest.get('primary_view') in ['viewer','scene'] else
                  {(v['path'],v['sha256']) for row in manifest['rows'] for v in row['images'].values()})
        observed = set()
        for item in evidence:
            if not isinstance(item, dict) or not item.get('receipt_ref') or (item.get('image_path'), item.get('image_sha256')) not in wanted:
                fail('Agent read evidence must bind each image hash and original receipt reference')
            observed.add((item['image_path'], item['image_sha256']))
        if observed != wanted:
            fail('Agent review requires actual read references for every primary image')
    if len(review.get('rows', [])) != 10:
        fail('Review must contain 10 rows')
    verdicts = []
    for expected, row in zip(manifest['rows'], review['rows']):
        for key in ['index', 'scene_name', 'frame_index', 'images']+(['scene_card'] if 'scene_card' in expected else []):
            if row.get(key) != expected[key]:
                fail('Review sample binding mismatch: ' + key)
        if row.get('inspected') is not True:
            fail('Sample not acknowledged as actually inspected: ' + str(row['index']))
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in JUDGMENTS):
            fail('Missing visual judgment for sample ' + str(row['index']))
        if row.get('verdict') not in ['pass', 'fail', 'inconclusive']:
            fail('Invalid sample verdict')
        verdicts.append(row['verdict'])
    aggregate = 'fail' if 'fail' in verdicts else ('inconclusive' if 'inconclusive' in verdicts else 'pass')
    if review.get('overall_verdict') != aggregate:
        fail('Overall verdict must match the ten per-sample verdicts')
    return manifest, aggregate

def finalize(run, review_path):
    run = Path(run).resolve()
    review = load(review_path)
    manifest, verdict = review_check(run, review)
    if (run / 'result.json').exists():
        fail('Already finalized; keep original result and use a new run directory for revisions')
    dump(run / 'visual-review.json', review)
    result = {'schema': 'mesh-m3-result/v1', 'evaluation_status': 'complete',
              'm3_verdict': verdict, 'demo': manifest['demo'], 'completed_at': utc(),
              'run_manifest_sha256': digest(run / 'run-manifest.json'),
              'review_sha256': digest(run / 'visual-review.json'),
              'goal_met': None, 'promotion_decision': 'requires_project_decision',
              'formal_m1': 'not_measured', 'm2': 'not_measured',
              'review_evidence_note': 'Human acknowledgment or agent receipt references; software checks bindings, not the truth of an inspection claim.'}
    dump(run / 'result.json', result)
    report(run, manifest, review, result)
    print(json.dumps(result, ensure_ascii=False))

def check(run):
    run = Path(run).resolve()
    checked_manifest(run)
    if not (run / 'result.json').exists():
        print(json.dumps({'evaluation_status': 'incomplete', 'reason': 'visual_review_pending'}))
        return 3
    result = load(run / 'result.json')
    manifest, verdict = review_check(run, load(run / 'visual-review.json'))
    if (result.get('schema') != 'mesh-m3-result/v1' or result.get('evaluation_status') != 'complete'
            or result.get('run_manifest_sha256') != digest(run / 'run-manifest.json')
            or result.get('review_sha256') != digest(run / 'visual-review.json')
            or result.get('m3_verdict') != verdict or result.get('demo') != manifest['demo']):
        fail('Result and original review binding mismatch')
    print(json.dumps(result, ensure_ascii=False))
    return 0

def report(run, manifest, review, result=None):
    data = {'manifest': manifest, 'review': review, 'result': result}
    template = (ROOT / 'report-template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    (Path(run) / 'index.html').write_text(template.replace('__PAYLOAD__', payload), encoding='utf-8')

def demo(out):
    import numpy as np
    import tempfile
    with tempfile.TemporaryDirectory(prefix='mesh-demo-') as tmp:
        folder = Path(tmp)
        scenes, hashes = [], {}
        for index in range(10):
            scene = f'SYNTHETIC-DEMO-{index:02d}'
            scenes.append(scene)
            xx, yy = np.meshgrid(np.arange(40) * .1, np.arange(20) * .1)
            labels = np.ones(xx.size)
            for offset, label in enumerate(LABELS):
                labels[offset*90:(offset+1)*90] = label
            gt = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size), labels)).astype('float32')
            pred = gt.copy()
            if index % 2 == 0:
                pred[100:200,3] = 1
            np.save(folder / f'{index}_gt.pcd.bin.npy', gt)
            np.save(folder / f'{index}_pred.pcd.bin.npy', pred)
            np.save(folder / f'{index}_mesh_gt.npy', np.column_stack((gt, np.ones(len(gt)))).astype('float32'))
            hashes[scene] = digest(folder / f'{index}_mesh_gt.npy')
            dump(folder / f'{index}_paths.json', {'scene_name': scene, 'datalink_frame': {'frame_index': 7}})
        protocol = {'protocol_id': 'SYNTHETIC-DEMO-NOT-REAL-EVALUATION', 'scene_order': scenes,
                    'scene_order_sha256': hashlib.sha256('\n'.join(scenes).encode()).hexdigest(),
                    'source_gt_hashes': hashes, 'frames': [7]*10}
        dump(folder / 'protocol.json', protocol)
        return render(folder, out, {'task_uid': 'SYNTHETIC-DEMO'}, folder / 'protocol.json', demo=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check local Python and dependencies')
    p = sub.add_parser('inspect', help='Validate completed eval vis inputs')
    p.add_argument('--vis', required=True, type=Path)
    p = sub.add_parser('render', help='Generate the fixed ten GT/PRED and difference images')
    p.add_argument('--vis', required=True, type=Path)
    p.add_argument('--identity', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--open', action='store_true')
    p = sub.add_parser('demo', help='Generate synthetic demo; no real task or model')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--open', action='store_true')
    p = sub.add_parser('finalize', help='Verify and bind completed actual visual review')
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--review', required=True, type=Path)
    p = sub.add_parser('check', help='0=complete, 3=review pending, 2=invalid')
    p.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    try:
        if sys.version_info < (3,10):
            fail('Python 3.10 or newer required')
        if args.command == 'doctor':
            missing = [name for name in ['numpy','PIL'] if importlib.util.find_spec(name) is None]
            print(json.dumps({'python': sys.version, 'executable': sys.executable, 'missing': missing,
                              'fixed_protocol': (ROOT / 'fixed10-scenes.json').is_file()}, ensure_ascii=False))
            return 2 if missing else 0
        if args.command == 'inspect':
            pairs, counts = inspect_vis(args.vis, load(ROOT / 'fixed10-scenes.json'))
            print(json.dumps({'status': 'inputs_valid', 'scenes': len(pairs), 'focus_support': counts}, ensure_ascii=False))
        elif args.command == 'render':
            output = render(args.vis, args.out, load(args.identity), ROOT / 'fixed10-scenes.json')
            if args.open: webbrowser.open((output / 'index.html').as_uri())
        elif args.command == 'demo':
            output = demo(args.out)
            if args.open: webbrowser.open((output / 'index.html').as_uri())
        elif args.command == 'finalize': finalize(args.run, args.review)
        elif args.command == 'check': return check(args.run)
        return 0
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
