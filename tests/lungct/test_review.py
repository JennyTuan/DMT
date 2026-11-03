import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from helpers import make_ct, SOURCE


class ReviewTests(unittest.TestCase):
    def setUp(self):
        from apps.lungct.service import Service
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);make_ct(self.root/'input')
        self.service=Service(self.root/'store',allowed_roots=[self.root])
        self.project=self.service.create_project('P','OP')['project_id']
        self.series=self.service.import_study(self.project,self.root/'input',SOURCE)['series'][0]
        self.service.select_series(self.project,self.series['study_key'],self.series['series_key'])
        self.draft=self.service.start_draft(self.project,self.series['series_key'],'OP')
        self.did=self.draft['draft_id']

    def add(self):
        return self.service.add_finding(self.project,self.did,[-6,-3,6],'OP')

    def revise(self,f,patch):
        return self.service.revise_finding(self.project,self.did,f['finding_id'],f['revision']['revision_id'],patch,'OP')

    def complete(self,**kw):
        d=self.service.get_draft(self.project,self.did)
        return self.service.complete_case(self.project,self.did,d['version'],'OP',browsed=True,**kw)

    def test_A03_10mm_6mm_physical_endpoints(self):
        f=self.add()
        f=self.revise(f,{'long_axis':[[-11,-3,6],[-1,-3,6]],'short_axis':[[-6,-6,6],[-6,0,6]],'state':'confirmed'})
        self.assertAlmostEqual(f['revision']['long_axis']['length_mm'],10,delta=.1)
        self.assertAlmostEqual(f['revision']['short_axis']['length_mm'],6,delta=.1)
        self.assertEqual(self.complete()['counts']['confirmed'],1)
        with self.assertRaises(ValueError):self.revise(f,{'side':'left'})

    def test_measurement_constraints_and_completion_reasons(self):
        f=self.add()
        with self.assertRaises(ValueError):self.complete()
        f=self.revise(f,{'state':'confirmed'})
        with self.assertRaises(ValueError):self.complete()
        for patch in [{'short_axis':[[-6,-6,6],[-6,0,6]]},
                      {'long_axis':[[-11,-3,6],[-1,-3,7.5]]},
                      {'long_axis':[[-11,-3,6],[-1,-3,6]],'short_axis':[[-6,-9,6],[-6,3,6]]},
                      {'long_axis':[[-11,-3,6],[-1,-3,6]],'short_axis':[[-8,-3,6],[-4,-3,6]]},
                      {'side':'right','lobe':'LUL'}, {'reason':'TEST PATIENT NAME'}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):self.revise(f,patch)
        f=self.revise(f,{'missing_reason':'not_measured'})
        self.assertEqual(self.complete()['counts']['confirmed'],1)

    def test_A07_stale_revision_undo_reopen_and_immutable_snapshot(self):
        from apps.lungct.service import Service
        f=self.add();original=deepcopy(f)
        f=self.revise(f,{'state':'confirmed','missing_reason':'not_measured','side':'left'})
        with self.assertRaisesRegex(ValueError,'过期'):self.revise(original,{'side':'right'})
        undo=self.service.undo_finding(self.project,self.did,f['finding_id'],f['revision']['revision_id'],'OP')
        self.assertEqual(undo['revision']['state'],'pending')
        f=self.revise(undo,{'state':'confirmed','missing_reason':'not_measured'})
        snap=self.complete();before=deepcopy(snap)
        reopened=self.service.reopen_case(self.project,snap['snapshot_id'],'OP');self.did=reopened['draft_id']
        f=self.revise(f,{'side':'right'})
        service=Service(self.root/'store',allowed_roots=[self.root])
        self.assertEqual(service.repo.read()['snapshots'][snap['snapshot_id']],before)
        self.assertEqual(service.get_draft(self.project,self.did)['findings'][0]['revision']['side'],'right')
        self.assertEqual(original['original'],f['original'])

    def test_A06_three_test_candidates_plus_manual(self):
        # Explicit synthetic protocol fixture: no inference, never A04 evidence.
        fs=[self.add() for _ in range(4)]
        with self.service.repo.transaction() as state:
            for f in fs[:3]:state['findings'][f['finding_id']]['source']='ai'
        fs[0]=self.revise(fs[0],{'state':'confirmed','missing_reason':'not_measured'})
        fs[1]=self.revise(fs[1],{'state':'excluded','reason':'false_positive'})
        fs[2]=self.revise(fs[2],{'state':'uncertain','reason':'insufficient_evidence'})
        with self.assertRaisesRegex(ValueError,'待复核'):self.complete()
        self.revise(fs[3],{'state':'confirmed','missing_reason':'not_measured'})
        snapshot=self.complete()
        self.assertEqual(snapshot['counts'],dict(ai=3,manual=1,confirmed=2,excluded=1,uncertain=1,pending=0))
        self.assertEqual(len(snapshot['findings']),4)

    def test_zero_confirmation_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):self.complete()
        self.assertEqual(self.complete(confirm_zero=True)['counts']['confirmed'],0)


if __name__=='__main__':unittest.main()
