import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_pointcloud_demo import compact_cloud


class PreviewPreparation(unittest.TestCase):
    def test_only_ignore_rows_removed_and_retained_rows_are_bit_identical(self):
        with tempfile.TemporaryDirectory(prefix='preview-prepare-') as directory:
            source, target = Path(directory) / 'source.npy', Path(directory) / 'target.npy'
            array = np.array([[1., -0., .3, 1], [4, 5, 6, 26], [7, 8, 9, 2]], dtype='<f4')
            np.save(source, array)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            record = compact_cloud(source, target)
            result = np.load(target, allow_pickle=False)
            self.assertEqual(result.tobytes(), array[array[:, 3] != 26].tobytes())
            self.assertEqual(record['original_rows'], 3)
            self.assertEqual(record['prepared_rows'], 2)
            self.assertEqual(record['excluded_label_26'], 1)
            self.assertEqual(record['original_sha256'], digest)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
