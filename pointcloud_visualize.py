"""Point-cloud evaluation artifacts -> equal-axis GT/PRED/Camera/LiDAR/Gaussian previews."""
import argparse
import hashlib
import html
import json
import math
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import five_view as shared
from scene_visualize import font
from view_camera import settings as camera_settings

RENDERER_VERSION = '1.0.0'
SUFFIXES = {'gt': '_gt.pcd.bin.npy', 'pred': '_pred.pcd.bin.npy',
            'camera': '_image.jpg', 'lidar': '_lidar.pcd.bin.npy',
            'gaussian': '_gaussian.pkl', 'metadata': '_paths.json'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Metadata exceeds the 8 MiB preview limit: ' + path.name)
    return json.loads(path.read_text(encoding='utf-8-sig'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + value)))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def files_for(vis, base):
    base = str(base)
    if not re.fullmatch(r'\d+', base):
        raise ValueError('Sample IDs must be numeric file prefixes')
    files = {key: Path(vis) / (base + suffix) for key, suffix in SUFFIXES.items()}
    for key, path in files.items():
        if not path.is_file():
            raise ValueError('Point-cloud preview requires ' + key + ': ' + str(path))
    calibration = Path(vis) / (base + '_sensor_param.json')
    if calibration.is_file():
        files['calibration'] = calibration
    return files


def read_cloud(path, semantic=True, max_points=200000):
    """Two bounded passes: validate/count, then deterministic stride of visible input rows."""
    if not isinstance(max_points, int) or isinstance(max_points, bool) or not 1 <= max_points <= 1000000:
        raise ValueError('max_points must be an integer in [1, 1000000]')
    source = np.load(path, mmap_mode='r', allow_pickle=False)
    if source.ndim != 2 or source.shape[1] != 4 or not len(source) or source.dtype.kind not in 'fiu':
        raise ValueError('Expected a nonempty numeric [N,4] point cloud: ' + str(path))
    count, excluded = 0, 0
    lower = upper = None
    classes = np.zeros(27, dtype=np.int64)
    chunk_size = 65536
    for start in range(0, len(source), chunk_size):
        block = source[start:start + chunk_size]
        if not np.isfinite(block).all():
            raise ValueError('Point cloud contains nonfinite values: ' + str(path))
        if semantic:
            labels = block[:, 3]
            if ((labels < 0) | (labels > 26) | (labels != np.floor(labels))).any():
                raise ValueError('Semantic labels must be integers in [0,26]')
            classes += np.bincount(labels.astype(np.int64), minlength=27)
            visible = block[labels != 26]
            excluded += int(np.count_nonzero(labels == 26))
        else:
            visible = block
        if len(visible):
            lo, hi = visible[:, :3].min(0), visible[:, :3].max(0)
            lower = lo if lower is None else np.minimum(lower, lo)
            upper = hi if upper is None else np.maximum(upper, hi)
            count += len(visible)
    stride = max(1, math.ceil(count / max_points))
    pieces, seen = [], 0
    for start in range(0, len(source), chunk_size):
        block = source[start:start + chunk_size]
        visible = block[block[:, 3] != 26] if semantic else block
        take = visible[(-seen) % stride::stride]
        if len(take):
            pieces.append(np.array(take, dtype=np.float64, copy=True))
        seen += len(visible)
    points = np.concatenate(pieces) if pieces else np.empty((0, 4), dtype=np.float64)
    stats = {'input_points': len(source), 'eligible_points': count, 'displayed_points': len(points),
             'excluded_label_26': excluded if semantic else 0,
             'stride': stride, 'sampling': 'every stride-th eligible row in original order',
             'bounds_xyz': None if lower is None else [lower.tolist(), upper.tolist()]}
    if semantic:
        stats['input_class_counts'] = {str(i): int(value) for i, value in enumerate(classes) if value}
    return points, stats


def bounds_corners(*cloud_stats):
    bounds = [item['bounds_xyz'] for item in cloud_stats if item['bounds_xyz'] is not None]
    if not bounds:
        raise ValueError('GT and prediction contain no visible semantic points after excluding label 26')
    lower = np.min([item[0] for item in bounds], axis=0)
    upper = np.max([item[1] for item in bounds], axis=0)
    return np.array([[x, y, z] for x in (lower[0], upper[0])
                     for y in (lower[1], upper[1]) for z in (lower[2], upper[2])])


def make_card(vis, base, output, max_points=200000, elevation_deg=30., azimuth_deg=8.):
    files = files_for(vis, base)
    meta = read_json(files['metadata'])
    if not isinstance(meta.get('scene_name'), str) or not meta['scene_name']:
        raise ValueError('paths.json must contain a scene_name')
    frame = meta.get('datalink_frame', {}).get('frame_index')
    if not ((isinstance(frame, int) and not isinstance(frame, bool)) or
            (isinstance(frame, list) and frame and all(isinstance(x, int) and not isinstance(x, bool) for x in frame))):
        raise ValueError('frame_index must be an integer or a nonempty integer list')
    camera = camera_settings(elevation_deg, azimuth_deg)
    gt, gt_stats = read_cloud(files['gt'], True, max_points)
    pred, pred_stats = read_cloud(files['pred'], True, max_points)
    lidar, lidar_stats = read_cloud(files['lidar'], False, max_points)
    gaussians = shared.read_gaussian(files['gaussian'])
    width, height, col = 2880, 1600, 720
    top, bottom, lidar_top = 98, 1504, 708
    image = Image.new('RGB', (width, height), shared.BG)
    draw = ImageDraw.Draw(image)
    draw.text((18, 12), '点云评测产物 · GT / Prediction / Camera / LiDAR / Gaussian', font=font(29), fill='#d9ded3')
    draw.text((18, 55), f'{meta["scene_name"]} · source {base} · 元数据帧 {json.dumps(frame)}', font=font(19), fill='#9aa590')
    view = shared.View(bounds_corners(gt_stats, pred_stats), (col - 8, bottom - top),
                       elevation_deg=elevation_deg, azimuth_deg=azimuth_deg)
    image.paste(shared.point_pane(gt, view), (4, top))
    image.paste(shared.point_pane(pred, view), (col + 4, top))
    with Image.open(files['camera']) as original:
        original.load()
        photo = original.convert('RGB')
        camera_size = list(photo.size)
        photo.thumbnail((col - 16, 482), Image.Resampling.LANCZOS)
        image.paste(photo, (2 * col + (col - photo.width) // 2, top + 58 + (482 - photo.height) // 2))
    lidar_view = shared.View(bounds_corners(lidar_stats), (col - 8, bottom - lidar_top),
                             elevation_deg=elevation_deg, azimuth_deg=azimuth_deg)
    image.paste(shared.point_pane(lidar, lidar_view, semantic=False), (2 * col + 4, lidar_top))
    gaussian_image, gaussian_stats = shared.gaussian_pane(gaussians, (col - 8, bottom - top),
        elevation_deg=elevation_deg, azimuth_deg=azimuth_deg)
    image.paste(gaussian_image, (3 * col + 4, top))
    draw = ImageDraw.Draw(image)
    for x in range(0, width, col):
        draw.rectangle((x, top, x + col - 1, bottom), outline='#3a4036', width=2)
    draw.line((2 * col, lidar_top, 3 * col, lidar_top), fill='#3a4036', width=2)
    for x, y, title, color in [(18, top + 12, 'GT · point cloud', '#75d77e'),
            (col + 18, top + 12, 'Prediction · point cloud', '#e78484'),
            (2 * col + 18, top + 12, 'Camera', '#d8ddd2'),
            (2 * col + 18, lidar_top + 12, 'LiDAR · intensity', '#d1b5e0'),
            (3 * col + 18, top + 12, 'Gaussian · ellipsoids', '#8ec0ec')]:
        draw.text((x, y), title, font=font(24), fill=color)
    for x, stats in [(18, gt_stats), (col + 18, pred_stats)]:
        draw.text((x, top + 49), f'显示 {stats["displayed_points"]:,}/{stats["eligible_points"]:,} 有效点 · stride {stats["stride"]}', font=font(17), fill='#a8b09e')
    draw.text((2 * col + 18, top + 553), '完整实车照片 · 无增强 / 无裁剪', font=font(19), fill='#a8b09e')
    draw.text((2 * col + 18, lidar_top + 48), f'显示 {len(lidar):,}/{lidar_stats["eligible_points"]:,} 导出点', font=font(18), fill='#a8b09e')
    draw.text((18, 1521), f'点云 / 非连续Mesh · XYZ 1:1:1 · 俯角 {elevation_deg:g}° / 方位 {azimuth_deg:g}° · GT/PRED共用范围和尺度', font=font(21), fill='#b3bda6')
    draw.text((18, 1556), '忽略label 26；超限时按原顺序等步长抽样，细小结构可能缺失 · Gaussian为导出参数椭球线框 · 不代表正式M1/M2/M3结论', font=font(19), fill='#b3bda6')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {'source_index': str(base), 'scene_name': meta['scene_name'], 'frame_index': frame,
            'profile': 'pointcloud-five-view/v1', 'size': [width, height], 'camera': camera,
            'clouds': {'gt': gt_stats, 'pred': pred_stats, 'lidar': lidar_stats},
            'gaussian': gaussian_stats, 'camera_source_size': camera_size,
            'source_files': {key: {'filename': path.name, 'sha256': sha(path)} for key, path in files.items()},
            'image_sha256': sha(output), 'formal_evaluation': False}


def generate(vis_dir, output_dir, indices=None, limit=3, max_points=200000,
             elevation_deg=30., azimuth_deg=8.):
    """Generate previews for chosen point-cloud exports without the fixed-ten Mesh protocol."""
    vis, out = Path(vis_dir).resolve(), Path(output_dir).resolve()
    camera = camera_settings(elevation_deg, azimuth_deg)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError('limit must be a positive integer')
    if not isinstance(max_points, int) or isinstance(max_points, bool) or not 1 <= max_points <= 1000000:
        raise ValueError('max_points must be an integer in [1,1000000]')
    available = sorted([path.name[:-11] for path in vis.glob('*_paths.json')
                        if re.fullmatch(r'\d+', path.name[:-11])], key=lambda value: (int(value), value))
    if not available:
        raise ValueError('No numeric *_paths.json groups found in vis')
    if indices is None:
        selected = [available[i] for i in np.linspace(0, len(available) - 1, min(limit, len(available)), dtype=int)]
    else:
        selected = [str(value) for value in indices]
        if not selected or len(set(selected)) != len(selected) or any(value not in available for value in selected):
            raise ValueError('Requested indices must be unique existing sample prefixes')
    inputs = [{key: {'filename': path.name, 'sha256': sha(path)}
               for key, path in files_for(vis, base).items()} for base in selected]
    transport = vis.parent / 'preview-provenance.json'
    if transport.is_file():
        read_json(transport)  # Bound metadata size before including it in the output.
    provenance = {'filename': transport.name, 'sha256': sha(transport)} if transport.is_file() else None
    fingerprint_data = {'renderer_version': RENDERER_VERSION, 'selected': selected,
                        'inputs': inputs, 'display_camera': camera, 'max_points': max_points,
                        'ignored_semantic_labels': [26], 'prepared_input_provenance': provenance}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if out.exists() and not out.is_dir():
        raise ValueError('Output must be a directory')
    if out.exists() and any(out.iterdir()):
        prior = read_json(out / 'pointcloud-manifest.json')
        if prior.get('request_fingerprint') != fingerprint:
            raise ValueError('Output belongs to different inputs or parameters; choose a new directory')
        for row in prior['samples']:
            image = (out / row['image']).resolve()
            if not image.is_relative_to(out) or sha(image) != row['image_sha256']:
                raise ValueError('Existing output image changed')
        return response(out, prior, reused=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pointcloud-preview-', dir=out.parent) as directory:
        stage = Path(directory) / 'run'
        stage.mkdir()
        rows = []
        for base, expected in zip(selected, inputs):
            relative = 'pointcloud-views/' + base + '_pointcloud.png'
            row = make_card(vis, base, stage / relative, max_points, camera['elevation_deg'], camera['azimuth_deg'])
            if row['source_files'] != expected:
                raise ValueError('Input changed while rendering')
            row['image'] = relative
            rows.append(row)
        manifest = {'schema': 'mesh-visualize.pointcloud-run/v1', 'renderer_version': RENDERER_VERSION,
                    'request_fingerprint': fingerprint, 'selection': selected, 'available_groups': len(available),
                    'display_camera': camera, 'max_points': max_points, 'samples': rows,
                    'prepared_input_provenance': provenance, 'formal_evaluation': False,
                    'model_quality_verdict': None, 'images_inspected_by_this_call': False}
        if provenance:
            if sha(transport) != provenance['sha256']:
                raise ValueError('Prepared input provenance changed while rendering')
            (stage / transport.name).write_bytes(transport.read_bytes())
        dump(stage / 'pointcloud-manifest.json', manifest)
        cards = ''.join('<article><h2>source ' + html.escape(row['source_index']) + '</h2><p>' +
                        html.escape(row['scene_name']) + ' · 元数据帧 ' + html.escape(json.dumps(row['frame_index'])) +
                        '</p><a href="' + row['image'] + '"><img src="' + row['image'] +
                        '" alt="GT、Prediction、相机、LiDAR和Gaussian点云评测预览"></a></article>' for row in rows)
        (stage / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>点云评测产物预览</title>'
            '<style>body{font:16px/1.7 system-ui;margin:24px auto;max-width:1500px;padding:0 20px;background:#111310;color:#d9ded3}'
            'article{margin:28px 0}img{width:100%;height:auto}p{overflow-wrap:anywhere}a{color:#8ec0ec}</style>'
            '<h1>点云评测产物预览</h1><p>GT/PRED/Camera/LiDAR/Gaussian；XYZ等比例。点云格式，不补造连续Mesh。'
            '超限时确定性抽样；过滤与抽样数量见图片和pointcloud-manifest.json。本页未执行正式固定十场景M3评价。</p>' + cards,
            encoding='utf-8')
        if out.exists():
            out.rmdir()  # Only an empty destination reaches this branch.
        stage.rename(out)
    return response(out, manifest, reused=False)


def response(out, manifest, reused):
    return {'schema': 'mesh-visualize.pointcloud-result/v1', 'status': 'generated', 'reused': reused,
            'formal_evaluation': False, 'model_quality_verdict': None,
            'display_camera': manifest['display_camera'], 'selection': manifest['selection'],
            'artifacts': {'report': str(out / 'index.html'), 'manifest': str(out / 'pointcloud-manifest.json'),
                          'primary_images': [{'source_index': row['source_index'], 'path': str(out / row['image']),
                                              'sha256': row['image_sha256']} for row in manifest['samples']]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--indices', help='Comma-separated numeric prefixes, e.g. 0,40,80')
    parser.add_argument('--limit', type=int, default=3, help='Default: three evenly spaced available groups')
    parser.add_argument('--max-points', type=int, default=200000, help='Per-cloud display cap; source files are not changed')
    parser.add_argument('--elevation-deg', type=float, default=30.)
    parser.add_argument('--azimuth-deg', type=float, default=8.)
    args = parser.parse_args()
    try:
        result = generate(args.vis, args.out, args.indices.split(',') if args.indices else None,
                          args.limit, args.max_points, args.elevation_deg, args.azimuth_deg)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        print(json.dumps({'schema': 'mesh-visualize.pointcloud-result/v1', 'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
