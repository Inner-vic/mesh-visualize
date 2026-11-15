import pickle,sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import five_view as f

class GaussianInput(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gaussian-parameter-test-')
        self.file=Path(self.temp.name)/'g.pkl'
        self.raw={'means':np.array([[10.,0.,0.]]),'scales':np.array([[.1,.2,.3]]),
                  'rots':np.array([[1.,0.,0.,0.]]),'opas':np.array([[.5]]),
                  'semantics':np.zeros((1,26))}
        self.raw['semantics'][0,1]=5
    def tearDown(self):self.temp.cleanup()
    def store(self):
        with self.file.open('wb') as p:pickle.dump(self.raw,p)
    def test_wxyz_identity_and_exported_semantics(self):
        self.store();g=f.read_gaussian(self.file)
        np.testing.assert_array_equal(g['rotation'][0],np.eye(3))
        self.assertEqual(g['labels'][0],1)
        np.testing.assert_array_equal(g['scales'],self.raw['scales'])
    def test_invalid_scale_or_opacity_rejected(self):
        self.raw['opas'][0,0]=1.5;self.store()
        with self.assertRaises(ValueError):f.read_gaussian(self.file)
        self.raw['opas'][0,0]=.5;self.raw['scales'][0,0]=0;self.store()
        with self.assertRaises(ValueError):f.read_gaussian(self.file)
    def test_empty_ignored_cloud_is_explicit(self):
        xyz=np.array([[5,0,0],[25,1,0]],dtype=float)
        view=f.View(xyz,(400,600))
        a=np.column_stack([xyz,[26,26]])
        out=f.point_pane(a,view)
        self.assertEqual(out.size,(400,600))

if __name__=='__main__':unittest.main()
