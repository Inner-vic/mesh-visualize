import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import view_camera as c
import five_view as f
import scene_visualize as s

class EqualAxisCamera(unittest.TestCase):
    def test_rotation_keeps_unit_xyz_lengths(self):
        for elevation in [0,15,30,45,85,90]:
            for azimuth in [-30,0,8,90,180,359]:
                b=c.basis(elevation,azimuth)
                np.testing.assert_allclose(b.T@b,np.eye(3),atol=1e-14)
                np.testing.assert_allclose(np.linalg.norm(np.eye(3)@b,axis=1),np.ones(3),atol=1e-14)
    def test_oblique_exposes_height_through_angle_only(self):
        z=np.array([0.,0.,1.])
        top=z@c.basis(90,8);oblique=z@c.basis(30,8)
        self.assertLess(np.linalg.norm(top[:2]),1e-14)
        self.assertGreater(np.linalg.norm(oblique[:2]),.8)
        self.assertAlmostEqual(np.linalg.norm(top),np.linalg.norm(oblique))
    def test_nonuniform_z_scale_rejected(self):
        xyz=np.array([[5.,0.,0.],[25.,1.,.1]])
        with self.assertRaises(ValueError):f.View(xyz,(400,600),zscale=5)
        with self.assertRaises(ValueError):s.view_transform(xyz,zscale=5)
        np.testing.assert_array_equal(f.View(xyz,(400,600)).stretch,[1,1,1])
    def test_invalid_angle_values_rejected(self):
        for elevation,azimuth in [(-1,0),(91,0),(float('nan'),0),(30,float('inf'))]:
            with self.assertRaises(ValueError):c.settings(elevation,azimuth)
    def test_azimuth_wrap_and_metadata(self):
        self.assertEqual(c.settings(30,368)['azimuth_deg'],8)
        self.assertEqual(c.settings()['axis_scale_xyz'],[1,1,1])

if __name__=='__main__':unittest.main()
