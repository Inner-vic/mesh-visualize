import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mesh_eval',ROOT/'mesh_eval.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mesh-acceptance-')
        self.run=Path(self.temp.name)/'含 空格 demo'
        with contextlib.redirect_stdout(io.StringIO()):module.demo(self.run)
        self.review=module.load(self.run/'review-template.json')
        self.review.update(reviewer='test fixture',completed_at='2026-11-13T10:00:00+08:00',summary='Synthetic software acceptance only.')
        for row in self.review['rows']:
            row.update(inspected=True,verdict='pass',**{key:'Synthetic test judgment' for key in module.JUDGMENTS})
        self.review['rows'][0]['verdict']='fail'
        self.review['overall_verdict']='fail'
    def tearDown(self):self.temp.cleanup()
    def rejects(self, review):
        with self.assertRaises(ValueError):module.review_check(self.run,review)
    def test_complete_negative_quality_and_portable_check(self):
        p=self.run/'input-review.json';module.dump(p,self.review)
        with contextlib.redirect_stdout(io.StringIO()):
            module.finalize(self.run,p)
            self.assertEqual(module.check(self.run),0)
        result=module.load(self.run/'result.json')
        self.assertEqual((result['evaluation_status'],result['m3_verdict']),('complete','fail'))
        self.assertTrue(result['demo']);self.assertIsNone(result['goal_met'])
        with self.assertRaises(ValueError):module.finalize(self.run,p)
    def test_pending_exit(self):
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(module.check(self.run),3)
    def test_missing_or_tampered_image(self):
        image=self.run/'images/0_diff.png'
        image.write_bytes(image.read_bytes()+b'tamper')
        with self.assertRaises(ValueError):module.checked_manifest(self.run)
        image.unlink()
        with self.assertRaises(OSError):module.checked_manifest(self.run)
    def test_missing_judgment_and_scene_mismatch(self):
        review=copy.deepcopy(self.review);review['rows'][5]['shape']='';self.rejects(review)
        review=copy.deepcopy(self.review);review['rows'][5]['scene_name']='different';self.rejects(review)
    def test_review_binding_and_aggregate(self):
        review=copy.deepcopy(self.review);review['run_manifest_sha256']='0'*64;self.rejects(review)
        review=copy.deepcopy(self.review);review['overall_verdict']='pass';self.rejects(review)
    def test_agent_needs_each_image_receipt(self):
        review=copy.deepcopy(self.review);review['reviewer_type']='agent';self.rejects(review)
        review['read_evidence']=[{'image_path':image['path'],'image_sha256':image['sha256'],'receipt_ref':'synthetic-test-receipt'}
                                 for row in review['rows'] for image in row['images'].values()]
        module.review_check(self.run,review)
        review['read_evidence']=review['read_evidence'][:1];self.rejects(review)
    def test_protocol_tamper(self):
        protocol=module.load(self.run/'protocol.json');protocol['frames'][0]=8;module.dump(self.run/'protocol.json',protocol)
        with self.assertRaises(ValueError):module.checked_manifest(self.run)
    def test_no_overwrite(self):
        with self.assertRaises(ValueError):module.demo(self.run)
    def test_identity_placeholder_and_hash(self):
        with self.assertRaises(ValueError):module.identity_check(module.load(ROOT/'identity.example.json'))
    def test_class_ids_not_color_difference(self):
        import numpy as np
        # Non-focus labels share a gray palette but remain different semantic IDs.
        a=np.array([[0,0,0,3]],dtype=float);b=np.array([[0,0,0,5]],dtype=float)
        x=module.raster(a,[0,0,0,0]);y=module.raster(b,[0,0,0,0])
        self.assertTrue((module.rgb(x)==module.rgb(y)).all());self.assertTrue((x!=y).all())

if __name__=='__main__':unittest.main()
