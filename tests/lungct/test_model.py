import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
from helpers import SOURCE, make_ct


class ProtocolFixture:
    """Test-only adapter; never exposed by the server or CLI."""
    def __init__(self,mode):self.mode=mode
    def metadata(self):return {'name':'SYNTHETIC_PROTOCOL_FIXTURE','version':'test','weight_sha256':None,'preprocessing_sha256':'test'}
    def predict(self,volume,geometry,threshold):
        if self.mode=='fail':raise MemoryError()
        candidates=[] if self.mode=='zero' else [dict(center_lps=[-6,-3,6],box_lps=[-8,-5,4,-4,-1,8],score=.8)]
        if self.mode=='partial':candidates.append(dict(center_lps=[999,0,0],box_lps=[0]*6,score=.9))
        return {'candidates':candidates,'model_to_lps':np.eye(4).tolist()}


class ModelTests(unittest.TestCase):
    def test_memory_profiles_are_explicit_and_have_distinct_provenance(self):
        from apps.lungct.model import MonaiAdapter
        import json
        with tempfile.TemporaryDirectory() as directory:
            bundle=Path(directory);(bundle/'models').mkdir();(bundle/'configs').mkdir()
            (bundle/'models/model.pt').write_bytes(b'configuration-test-only')
            (bundle/'configs/metadata.json').write_text(json.dumps({'version':'0.6.9'}))
            standard=MonaiAdapter(bundle).metadata()
            low=MonaiAdapter(bundle,profile='low-memory').metadata()
            self.assertEqual(standard['preprocessing']['patch'],[512,512,192])
            self.assertEqual(low['preprocessing']['patch'],[256,256,96])
            self.assertNotEqual(standard['preprocessing_sha256'],low['preprocessing_sha256'])
            self.assertEqual(standard['weight_sha256'],low['weight_sha256'])
            with self.assertRaises(ValueError):MonaiAdapter(bundle,profile='unknown')

    def setUp(self):
        from apps.lungct.service import Service
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);make_ct(self.root/'input')
        self.service=Service(self.root/'store',allowed_roots=[self.root])
        self.project=self.service.create_project('P','OP')['project_id']
        self.series=self.service.import_study(self.project,self.root/'input',SOURCE)['series'][0]
        self.service.select_series(self.project,self.series['study_key'],self.series['series_key'])

    def run_model(self,key,adapter):
        self.service.model=adapter
        run=self.service.start_run(self.project,self.series['series_key'],key)
        for _ in range(100):
            result=self.service.get_run(self.project,run['run_id'])
            if result['state'] in ('failed','succeeded'):return result
            time.sleep(.02)
        self.fail('Model protocol task did not finish')

    def test_A05_missing_failure_and_true_zero_are_distinct(self):
        missing=self.run_model('missing',None)
        failed=self.run_model('failed',ProtocolFixture('fail'))
        zero=self.run_model('zero',ProtocolFixture('zero'))
        self.assertEqual(missing['error_code'],'MODEL_NOT_CONFIGURED')
        self.assertEqual(failed['error_code'],'OUT_OF_MEMORY')
        self.assertIsNone(missing['candidate_count']);self.assertIsNone(failed['candidate_count'])
        self.assertEqual(zero['candidate_count'],0);self.assertTrue(zero['complete'])
        self.assertEqual(len({r['message'] for r in (missing,failed,zero)}),3)

    def test_partial_results_rejected_and_request_is_idempotent(self):
        result=self.run_model('partial',ProtocolFixture('partial'))
        self.assertEqual(result['state'],'failed');self.assertEqual(result['finding_ids'],[])
        self.assertEqual(self.service.start_run(self.project,self.series['series_key'],'partial')['run_id'],result['run_id'])

    def test_new_run_cannot_overwrite_review_branch(self):
        run=self.run_model('one',ProtocolFixture('one'))
        d=self.service.start_draft(self.project,self.series['series_key'],'OP',run['run_id'])
        f=d['findings'][0]
        self.service.revise_finding(self.project,d['draft_id'],f['finding_id'],f['revision']['revision_id'],{'state':'confirmed','missing_reason':'not_measured'},'OP')
        before=self.service.get_draft(self.project,d['draft_id'])
        self.run_model('two',ProtocolFixture('zero'))
        self.assertEqual(self.service.get_draft(self.project,d['draft_id']),before)

    def test_real_adapter_refuses_missing_weights(self):
        from apps.lungct.model import MonaiAdapter
        adapter=MonaiAdapter(self.root/'missing')
        with self.assertRaisesRegex(ValueError,'WEIGHTS_MISSING'):adapter.metadata()

    def test_restart_marks_interrupted_task_failed_not_zero(self):
        from apps.lungct.service import Service
        run=self.run_model('interrupted',None)
        with self.service.repo.transaction() as state:
            state['runs'][run['run_id']].update(state='running',error_code=None,message='正在分析')
        restarted=Service(self.root/'store',allowed_roots=[self.root])
        result=restarted.get_run(self.project,run['run_id'])
        self.assertEqual(result['error_code'],'INTERRUPTED')
        self.assertEqual(result['state'],'failed');self.assertIsNone(result['candidate_count'])


if __name__=='__main__':unittest.main()
