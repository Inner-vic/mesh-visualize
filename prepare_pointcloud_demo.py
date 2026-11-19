"""Prepare small, traceable point-cloud demo inputs; source files are read-only."""
import argparse
import ast
import hashlib
import json
import math
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def compact_cloud(source, target):
    """Keep every original float32 row except semantic ignore label 26; no sampling."""
    digest = hashlib.sha256()
    counts, kept = {}, 0
    with Path(source).open('rb') as stream, tempfile.TemporaryFile() as spool:
        prefix = stream.read(8)
        if prefix[:6] != b'\x93NUMPY' or prefix[6] not in (1, 2, 3):
            raise ValueError('Unsupported NPY file')
        width = 2 if prefix[6] == 1 else 4
        length = stream.read(width)
        header_length = int.from_bytes(length, 'little')
        if header_length > 65536:
            raise ValueError('NPY header exceeds limit')
        header_bytes = stream.read(header_length)
        if len(header_bytes) != header_length:
            raise ValueError('Truncated NPY header')
        header = ast.literal_eval(header_bytes.decode('utf-8' if prefix[6] == 3 else 'latin1'))
        shape = header['shape']
        if (header['fortran_order'] or header['descr'] not in ('<f4', '=f4') or
                sys.byteorder != 'little' or len(shape) != 2 or shape[1] != 4):
            raise ValueError('Expected C-order little-endian float32 [N,4]')
        digest.update(prefix + length + header_bytes)
        seen = 0
        while True:
            block = stream.read(65536 * 16)
            if not block:
                break
            if len(block) % 16:
                raise ValueError('Truncated cloud data')
            digest.update(block)
            pieces = []
            for index, row in enumerate(struct.iter_unpack('<4f', block)):
                if not all(math.isfinite(value) for value in row):
                    raise ValueError('Cloud contains nonfinite values')
                label = row[3]
                if label != int(label) or not 0 <= label <= 26:
                    raise ValueError('Invalid semantic label')
                label = int(label)
                counts[label] = counts.get(label, 0) + 1
                if label != 26:
                    pieces.append(block[index * 16:(index + 1) * 16])
                    kept += 1
                seen += 1
            spool.write(b''.join(pieces))
        if seen != shape[0]:
            raise ValueError('Cloud byte length does not match NPY shape')
        text = repr({'descr': '<f4', 'fortran_order': False, 'shape': (kept, 4)})
        padding = (-(10 + len(text) + 1)) % 64
        output_header = (text + ' ' * padding + '\n').encode('latin1')
        with Path(target).open('wb') as output:
            output.write(b'\x93NUMPY\x01\x00' + struct.pack('<H', len(output_header)) + output_header)
            spool.seek(0)
            shutil.copyfileobj(spool, output, length=1024 * 1024)
    return {'original_sha256': digest.hexdigest(), 'original_rows': seen, 'prepared_rows': kept,
            'excluded_label_26': counts.get(26, 0), 'input_class_counts': counts,
            'prepared_sha256': sha(target), 'transformation': 'remove label 26 only; retain all other original row bytes/order'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--indices', default='0,40,80')
    args = parser.parse_args()
    vis, out = args.vis.resolve(), args.out.resolve()
    if out == vis or vis in out.parents:
        raise ValueError('Prepared inputs must be outside the source vis directory')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Choose a new empty preparation directory')
    archive_path = out.with_suffix('.zip')
    if archive_path.exists():
        raise ValueError('Archive already exists; choose a fresh output name')
    indices = args.indices.split(',')
    if not indices or len(set(indices)) != len(indices) or any(not value.isdecimal() for value in indices):
        raise ValueError('Indices must be unique numeric prefixes')
    output_vis = out / 'vis'
    output_vis.mkdir(parents=True, exist_ok=True)
    records = []
    for base in indices:
        record = {'source_index': base, 'files': {}}
        for suffix in ['_gt.pcd.bin.npy', '_pred.pcd.bin.npy']:
            original, target = vis / (base + suffix), output_vis / (base + suffix)
            record['files'][original.name] = compact_cloud(original, target)
        for suffix in ['_image.jpg', '_lidar.pcd.bin.npy', '_gaussian.pkl', '_paths.json', '_sensor_param.json']:
            original, target = vis / (base + suffix), output_vis / (base + suffix)
            shutil.copyfile(original, target)
            original_hash, target_hash = sha(original), sha(target)
            if original_hash != target_hash:
                raise ValueError('Copied input differs from source')
            record['files'][original.name] = {'original_sha256': original_hash,
                'prepared_sha256': target_hash, 'transformation': 'byte-identical copy'}
        records.append(record)
        print(json.dumps({'prepared_index': base, 'clouds': {name: {key: value[key] for key in ['original_rows', 'prepared_rows', 'excluded_label_26']}
              for name, value in record['files'].items() if 'original_rows' in value}}), flush=True)
    provenance = {'schema': 'mesh-visualize.prepared-pointcloud-inputs/v1', 'source_vis': str(vis),
        'indices': indices, 'source_files_modified': False, 'training_or_inference_performed': False,
        'synthetic': False, 'semantic_exclusion': [26], 'sampling_performed': False, 'records': records}
    (out / 'preview-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file():
                archive.write(path, 'pointcloud-demo-inputs/' + path.relative_to(out).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise ValueError('Archive CRC failed')
    print(json.dumps({'archive': str(archive_path), 'bytes': archive_path.stat().st_size,
                      'sha256': sha(archive_path), 'source_files_modified': False}), flush=True)


if __name__ == '__main__':
    main()
