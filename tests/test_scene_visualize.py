import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_visualize as s

class ProjectionChecks(unittest.TestCase):
    def setUp(self):
        self.sensor={'sensor_param':{'cam':{
            'dist_model':'equidistant','proj_model':'pinhole',
            'q_vcs_cam':{'w':1,'x':0,'y':0,'z':0},'t_vcs_cam':{'x':0,'y':0,'z':0},
            'dist_param':{'k1':0,'k2':0,'k3':0,'k4':0},
            'proj_param':{'fu':50,'fv':40,'cu':50,'cv':40},'resolution':{'ru':100,'rv':80}}}}
    def test_optical_axis_offaxis_and_rear_points(self):
        a=np.array([[0,0,1,1],[1,0,1,1],[0,0,-1,1]],dtype=float)
        u,v,z,mask=s.project(a,self.sensor)
        self.assertAlmostEqual(u[0],50);self.assertAlmostEqual(v[0],40)
        self.assertAlmostEqual(u[1],50+50*np.pi/4)
        self.assertTrue(mask[0]);self.assertTrue(mask[1]);self.assertFalse(mask[2])
    def test_visual_transforms_never_mutate_raw_points(self):
        a=np.array([[5,-2,-.1,1],[25,2,.2,2],[10,1,0,4]],dtype=float);original=a.copy()
        s.view_transform(a);s.project(a,self.sensor)
        np.testing.assert_array_equal(a,original)
    def test_empty_camera_projection_retains_empty(self):
        x,y,labels=s.nearest_pixels(np.array([]),np.array([]),np.array([]),np.array([],dtype=int),100,100)
        self.assertEqual(len(x),0);self.assertEqual(len(y),0);self.assertEqual(len(labels),0)
    def test_other_camera_model_is_explicitly_unsupported(self):
        self.sensor['sensor_param']['cam']['dist_model']='unverified-model'
        with self.assertRaises(ValueError):s.project(np.array([[0,0,1,1]],dtype=float),self.sensor)

if __name__=='__main__':unittest.main()
