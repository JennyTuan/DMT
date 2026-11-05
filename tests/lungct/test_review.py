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

    def test_display_numbers_remain_stable_after_more_findings_and_restart(self):
        original=[self.add() for _ in range(10)]
        records=self.service.get_draft(self.project,self.did)['findings']
        by_id={f['finding_id']:f['label'] for f in records}
        self.assertEqual([by_id[f['finding_id']] for f in original],[f'N-{i:03d}' for i in range(1,11)])

    def test_redrawing_long_axis_clears_dependent_short_axis(self):
        f=self.add();f=self.revise(f,{'long_axis':[[-11,-3,6],[-1,-3,6]],'short_axis':[[-6,-6,6],[-6,0,6]]})
        updated=self.revise(f,{'long_axis':[[-11,-3,6],[-1,-2,6]]})
        self.assertIsNone(updated['revision']['short_axis'])
        self.assertEqual(updated['revision']['missing_reason'],'not_measured')
        history=self.service.finding_history(self.project,self.did,f['finding_id'])
        self.assertEqual(history[1]['short_axis']['length_mm'],6)

    def test_contour_creation_edit_undo_and_export(self):
        import json
        outline=[[-9,-6,6],[-3,-6,6],[-3,0,6],[-9,0,6]]
        create=lambda vertices:self.service.add_finding(self.project,self.did,[-6,-3,6],'OP',geometry={'contour':vertices})
        for invalid in [outline[:2], [outline[i] for i in (0,2,1,3)], [*outline[:3],[-9,0,7.5]]]:
            with self.assertRaises(ValueError):create(invalid)
        self.assertEqual(self.service.get_draft(self.project,self.did)['findings'],[])
        finding=create(outline)
        self.assertEqual(finding['revision']['contour']['points_lps'],outline)
        new_outline=[*outline[:3],[-10,0,6]]
        edited=self.revise(finding,{'contour':new_outline})
        self.assertEqual(edited['finding_id'],finding['finding_id'])
        self.assertEqual(edited['original'],finding['original'])
        with self.assertRaisesRegex(ValueError,'过期'):self.revise(finding,{'contour':outline})
        restored=self.service.undo_finding(self.project,self.did,edited['finding_id'],edited['revision']['revision_id'],'OP')
        self.assertEqual(restored['revision']['contour']['points_lps'],outline)
        self.revise(restored,{'state':'confirmed','missing_reason':'not_measured'})
        snap=self.complete()
        package=self.service.export_snapshots(self.project,[snap['snapshot_id']])
        data=json.loads((Path(package['output_directory'])/'review.json').read_text(encoding='utf-8'))
        observation=data['snapshots'][0]['observations'][0]['adopted_revision']
        self.assertEqual(observation['contour']['points_lps'],outline)
        reopened=self.service.reopen_case(self.project,snap['snapshot_id'],'OP');self.did=reopened['draft_id']
        moved=self.revise(reopened['findings'][0],{'center_lps':[-6,-3,7.5],'slice_key':self.series['slice_keys'][5]})
        self.assertIsNone(moved['revision']['contour'])
        self.assertEqual(self.service.repo.read()['snapshots'][snap['snapshot_id']],snap)

    def test_latest_reopened_draft_is_selected_by_time_not_uuid(self):
        from unittest.mock import patch
        with patch('apps.lungct.review.uid',return_value='snapshot_test'):
            snapshot=self.complete(confirm_zero=True)
        with patch('apps.lungct.review.uid',return_value='draft_0000'):
            newest=self.service.reopen_case(self.project,snapshot['snapshot_id'],'OP')
        self.assertEqual(self.service.state(self.project)['drafts'][-1]['draft_id'],newest['draft_id'])
        with patch('apps.lungct.review.uid',return_value='draft_zzzz'):
            second=self.service.reopen_case(self.project,snapshot['snapshot_id'],'OP')
        self.assertEqual(self.service.start_draft(self.project,self.series['series_key'],'OP')['draft_id'],second['draft_id'])


if __name__=='__main__':unittest.main()
