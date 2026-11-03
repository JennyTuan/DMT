import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from helpers import SOURCE,make_ct


class ExportTests(unittest.TestCase):
    def test_model_profile_and_runtime_export_without_private_fields(self):
        from apps.lungct.export import run_export
        result=run_export(dict(run_id='run_test',model=dict(name='MONAI',execution_profile='low-memory',
            software_version='0.1.0',adapter_sha256='sha',private_path='SECRET_PATH',
            preprocessing=dict(patch=[256,256,96],private_path='SECRET_PATH'),
            runtime=dict(torch='2.4.1+cu121',device='GPU',cuda_peak_allocated_bytes=123,patient_name='SECRET_NAME'))))
        self.assertEqual(result['model']['execution_profile'],'low-memory')
        self.assertEqual(result['model']['preprocessing']['patch'],[256,256,96])
        self.assertEqual(result['model']['runtime']['torch'],'2.4.1+cu121')
        self.assertNotIn('SECRET',json.dumps(result))

    def setUp(self):
        from apps.lungct.service import Service
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.service=Service(self.root/'store',allowed_roots=[self.root])
        self.project=self.service.create_project('P','OP')['project_id']

    def case(self,n,confirmed=0,finish=True):
        folder=self.root/f'input{n}';make_ct(folder)
        s=self.service.import_study(self.project,folder,SOURCE)['series'][0]
        self.service.select_series(self.project,s['study_key'],s['series_key'])
        d=self.service.start_draft(self.project,s['series_key'],'OP')
        for i in range(confirmed):
            f=self.service.add_finding(self.project,d['draft_id'],[-6,-3,6],'OP')
            self.service.revise_finding(self.project,d['draft_id'],f['finding_id'],f['revision']['revision_id'],{'state':'confirmed','missing_reason':'not_measured'},'OP')
        snap=None
        if finish:
            draft=self.service.get_draft(self.project,d['draft_id'])
            snap=self.service.complete_case(self.project,d['draft_id'],draft['version'],'OP',browsed=True,confirm_zero=True)
        return s,d,snap

    def test_A08_counts_zero_denominator_hashes_bom_and_lookup(self):
        s,_,snap=self.case(1,2);self.case(2);self.case(3,finish=False)
        preview=self.service.export_preview(self.project)
        self.assertEqual(len(preview['snapshot_ids']),2);self.assertEqual(len(preview['skipped']),1)
        package=self.service.export_snapshots(self.project,preview['snapshot_ids'])
        folder=self.service.root/'exports'/package['export_id']
        self.assertEqual(Path(package['output_directory']),folder)
        self.assertTrue((folder/'studies.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
        with (folder/'studies.csv').open(encoding='utf-8-sig',newline='') as f:studies=list(csv.DictReader(f))
        with (folder/'nodules.csv').open(encoding='utf-8-sig',newline='') as f:nodules=list(csv.DictReader(f))
        review=json.loads((folder/'review.json').read_text(encoding='utf-8'))
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(studies),2);self.assertEqual(len(nodules),2)
        self.assertEqual(nodules[0]['long_mm'],'');self.assertEqual(studies[0]['ai_candidate_count'],'')
        for name,sha in manifest['files'].items():self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),sha)
        self.assertEqual(manifest['counts']['nodules'],len(nodules))
        row=nodules[0];hit=self.service.lookup_finding(self.project,row['study_key'],row['finding_id'])
        self.assertEqual(hit['slice_key'],row['slice_key'])
        all_text='\n'.join(p.read_text(encoding='utf-8-sig') for p in folder.iterdir())
        for forbidden in [str(self.root),'PatientName','PixelData','SYNTHETIC-SUBJECT']:
            self.assertNotIn(forbidden,all_text)
        self.assertEqual(len(review['snapshots']),2)

    def test_snapshot_and_project_boundaries_and_unique_packages(self):
        _,_,snap=self.case(1,1)
        other=self.service.create_project('Q','OP')['project_id']
        with self.assertRaises(ValueError):self.service.export_snapshots(other,[snap['snapshot_id']])
        with self.assertRaises(ValueError):self.service.export_snapshots(self.project,['draft_unknown'])
        a=self.service.export_snapshots(self.project,[snap['snapshot_id']]);b=self.service.export_snapshots(self.project,[snap['snapshot_id']])
        self.assertNotEqual(a['export_id'],b['export_id'])
        with self.service.repo.transaction() as state:state['snapshots'][snap['snapshot_id']]['operator']='MODIFIED'
        with self.assertRaisesRegex(ValueError,'校验'):self.service.export_snapshots(self.project,[snap['snapshot_id']])

    def test_write_failure_never_reports_partial_success(self):
        _,_,snap=self.case(1,1)
        with patch('apps.lungct.export.os.replace',side_effect=OSError('TEST DISK FULL')):
            with self.assertRaises(OSError):self.service.export_snapshots(self.project,[snap['snapshot_id']])
        self.assertEqual(self.service.repo.read()['exports'],{})
        self.assertFalse(any((self.service.root/'exports').glob('export_*')))


if __name__=='__main__':unittest.main()
