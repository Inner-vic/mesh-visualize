import hashlib
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pointcloud_visualize as p


class BoundedCloudInput(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pointcloud-input-')
        self.path = Path(self.temp.name) / 'cloud.npy'

    def tearDown(self):
        self.temp.cleanup()

    def test_filter_and_sampling_preserve_source_and_full_bounds(self):
        array = np.column_stack((np.arange(20), np.zeros(20), np.zeros(20), np.ones(20))).astype('float32')
        array[3, 3] = 26
        np.save(self.path, array)
        original = p.sha(self.path)
        points, stats = p.read_cloud(self.path, max_points=3)
        np.testing.assert_array_equal(points, array[array[:, 3] != 26][::7])
        self.assertEqual(stats['excluded_label_26'], 1)
        self.assertEqual(stats['bounds_xyz'][1][0], 19)
        self.assertEqual(original, p.sha(self.path))

    def test_stride_is_stable_across_chunk_boundary(self):
        array = np.zeros((66000, 4), dtype='float32')
        array[:, 0] = np.arange(len(array))
        array[:, 3] = 1
        array[::11, 3] = 26
        np.save(self.path, array)
        points, stats = p.read_cloud(self.path, max_points=23)
        np.testing.assert_array_equal(points, array[array[:, 3] != 26][::stats['stride']])
        self.assertLessEqual(len(points), 23)

    def test_bad_labels_and_nonfinite_values_are_rejected(self):
        for row in [[1, 2, 3, 1.5], [1, 2, 3, 27], [1, 2, np.nan, 26]]:
            np.save(self.path, np.array([row], dtype='float32'))
            with self.assertRaises(ValueError):
                p.read_cloud(self.path)

    def test_lidar_intensity_26_is_retained(self):
        np.save(self.path, np.array([[1, 2, 3, 26]], dtype='float32'))
        points, stats = p.read_cloud(self.path, semantic=False)
        self.assertEqual(len(points), 1)
        self.assertEqual(stats['excluded_label_26'], 0)


class PointcloudRun(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pointcloud-run-')
        self.root = Path(self.temp.name)
        self.vis = self.root / 'vis'
        self.vis.mkdir()
        for index in range(5):
            base = str(index)
            cloud = np.array([[5, -1, 0, 1], [15, 1, .1, 2], [25, 0, -.1, 1]], dtype='float32')
            np.save(self.vis / (base + '_gt.pcd.bin.npy'), cloud)
            np.save(self.vis / (base + '_pred.pcd.bin.npy'), cloud)
            np.save(self.vis / (base + '_lidar.pcd.bin.npy'), cloud)
            Image.new('RGB', (320, 180), '#90a4b5').save(self.vis / (base + '_image.jpg'))
            (self.vis / (base + '_paths.json')).write_text(json.dumps({'scene_name': 'test-scene-' + base,
                'datalink_frame': {'frame_index': [index, index + 1, index + 2, index + 3]}}), encoding='utf-8')
            gaussian = {'means': np.array([[12., 0., 0.]]), 'scales': np.array([[.3, .5, .2]]),
                        'rots': np.array([[1., 0., 0., 0.]]), 'opas': np.array([.8]),
                        'semantics': np.zeros((1, 26))}
            gaussian['semantics'][0, 1] = 1
            with (self.vis / (base + '_gaussian.pkl')).open('wb') as stream:
                pickle.dump(gaussian, stream)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_api_handles_temporal_metadata_without_mesh_and_reuses_verified_images(self):
        out = self.root / 'out'
        result = p.generate(self.vis, out)
        self.assertEqual(result['selection'], ['0', '2', '4'])
        self.assertFalse(result['formal_evaluation'])
        self.assertEqual(result['display_camera']['axis_scale_xyz'], [1., 1., 1.])
        manifest = p.read_json(out / 'pointcloud-manifest.json')
        self.assertEqual(manifest['samples'][0]['frame_index'], [0, 1, 2, 3])
        self.assertFalse(manifest['images_inspected_by_this_call'])
        self.assertEqual(len(result['artifacts']['primary_images']), 3)
        self.assertTrue(p.generate(self.vis, out)['reused'])
        with self.assertRaises(ValueError):
            p.generate(self.vis, out, elevation_deg=45)
        image = Path(result['artifacts']['primary_images'][0]['path'])
        image.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            p.generate(self.vis, out)

    def test_missing_modalities_fail_without_publishing(self):
        (self.vis / '0_gaussian.pkl').unlink()
        with self.assertRaises(ValueError):
            p.generate(self.vis, self.root / 'out', indices=[0])
        self.assertFalse((self.root / 'out').exists())

    def test_changed_source_cannot_reuse_old_run(self):
        out = self.root / 'out'
        p.generate(self.vis, out, indices=[0])
        np.save(self.vis / '0_pred.pcd.bin.npy', np.array([[5, 0, 0, 1]], dtype='float32'))
        with self.assertRaises(ValueError):
            p.generate(self.vis, out, indices=[0])


if __name__ == '__main__':
    unittest.main()
