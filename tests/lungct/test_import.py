import tempfile
import unittest
from pathlib import Path
import numpy as np
import pydicom
from helpers import make_ct, SOURCE


class ImportTests(unittest.TestCase):
    def setUp(self):
        from apps.lungct.service import Service
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.input = self.root/'input'
        self.service = Service(self.root/'store', allowed_roots=[self.root])
        self.project = self.service.create_project('LUNG-01', 'READER-1')['project_id']

    def load(self, **kw):
        make_ct(self.input, **kw)
        return self.service.import_study(self.project, self.input, SOURCE)

    def test_A01_geometry_order_dedup_and_project_isolation(self):
        study,_=make_ct(self.input/'thin')
        make_ct(self.input/'scout', study=study, count=2, localizer=True)
        first=self.service.import_study(self.project,self.input,SOURCE)
        again=self.service.import_study(self.project,self.input,SOURCE)
        self.assertEqual(first,again); self.assertEqual(len(first['studies']),1)
        valid=[s for s in first['series'] if s['eligible']]
        self.assertEqual(len(valid),1); s=valid[0]
        self.assertEqual(s['geometry']['locations'],list(np.arange(9)*1.5))
        self.assertEqual(s['geometry']['spacing'],[.75,.5])
        self.assertTrue(any('LOCALIZER' in x['qc_codes'] for x in first['series']))
        selected=self.service.select_series(self.project,s['study_key'],s['series_key'])
        self.assertEqual(selected['series_key'],s['series_key'])
        second=self.service.create_project('OTHER','READER-1')['project_id']
        with self.assertRaisesRegex(ValueError,'所属项目'):
            self.service.select_series(second,s['study_key'],s['series_key'])
        self.assertNotEqual(self.service.import_study(second,self.input,SOURCE)['studies'][0]['subject_key'],first['studies'][0]['subject_key'])

    def test_conflicting_uid_rejects_atomic_import(self):
        self.load()
        p=next(self.input.glob('*.dcm'));d=pydicom.dcmread(p);d.RescaleIntercept=-900;d.save_as(p,enforce_file_format=True)
        with self.assertRaisesRegex(ValueError,'UID_CONFLICT'):
            self.service.import_study(self.project,self.input,SOURCE)

    def test_requires_authorization_and_allowed_directory(self):
        make_ct(self.input)
        for key in ['authorized','deidentified','pixels_checked','adult_chest','noncontrast']:
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.service.import_study(self.project,self.input,{**SOURCE,key:False})
        with self.assertRaises(ValueError):
            self.service.import_study(self.project,self.root.parent,SOURCE)

    def test_phi_name_and_burned_pixels_rejected(self):
        make_ct(self.input,name='TEST^IDENTITY')
        with self.assertRaisesRegex(ValueError,'PHI'):
            self.service.import_study(self.project,self.input,SOURCE)
        for p in self.input.glob('*.dcm'):
            d=pydicom.dcmread(p);d.PatientName='';d.BurnedInAnnotation='YES';d.save_as(p,enforce_file_format=True)
        with self.assertRaisesRegex(ValueError,'BURNED'):
            self.service.import_study(self.project,self.input,SOURCE)

    def test_nonuniform_tilt_missing_geometry_and_contrast_are_blocked(self):
        cases=[('gap',dict(positions=[0,1.5,3,4.5,7,8.5,10,11.5,13]),'IRREGULAR_SPACING'),
               ('tilt',dict(orientation=(1,0,0,0,.98,.199)),'TILT'),
               ('duplicate',dict(positions=[0,1.5,3,3,6,7.5,9,10.5,12]),'GEOMETRY')]
        for label,kw,code in cases:
            with self.subTest(label=label):
                path=self.root/label;make_ct(path,**kw)
                result=self.service.import_study(self.project,path,SOURCE)
                self.assertFalse(result['series'][0]['eligible'])
                self.assertIn(code,result['series'][0]['qc_codes'])
                s=result['series'][0]
                with self.assertRaises(ValueError):self.service.select_series(self.project,s['study_key'],s['series_key'])
        for attr,value in [('PixelSpacing',None),('ContrastBolusAgent','contrast'),('SliceThickness',3.0)]:
            path=self.root/attr;make_ct(path)
            for p in path.glob('*.dcm'):
                d=pydicom.dcmread(p)
                if value is None:delattr(d,attr)
                else:setattr(d,attr,value)
                d.save_as(p,enforce_file_format=True)
            self.assertFalse(self.service.import_study(self.project,path,SOURCE)['series'][0]['eligible'])

    def test_persistence_and_source_mapping(self):
        from apps.lungct.service import Service
        r=self.load();s=r['series'][0]
        self.service.select_series(self.project,s['study_key'],s['series_key'])
        reopened=Service(self.root/'store',allowed_roots=[self.root])
        self.assertEqual(reopened.state(self.project)['selected_series'],s['series_key'])
        v,g=reopened.volume(self.project,s['series_key'])
        self.assertEqual(v.shape,(9,64,64));self.assertEqual(float(v[0,0,0]),-924)
        self.assertEqual(len(set(s['slice_keys'])),9)

    def test_same_study_with_different_subject_series_is_rejected(self):
        study,_=make_ct(self.input/'one')
        self.service.import_study(self.project,self.input/'one',SOURCE)
        make_ct(self.input/'two',study=study)
        for p in (self.input/'two').glob('*.dcm'):
            d=pydicom.dcmread(p);d.PatientID='DIFFERENT-SUBJECT';d.save_as(p,enforce_file_format=True)
        with self.assertRaisesRegex(ValueError,'SUBJECT_CONFLICT'):
            self.service.import_study(self.project,self.input/'two',SOURCE)
        other=self.service.create_project('OTHER','OP')['project_id']
        with self.assertRaisesRegex(ValueError,'SUBJECT_CONFLICT'):
            self.service.import_study(other,self.input,SOURCE)
        self.assertEqual(len(self.service.state(other)['studies']),0)

    def test_implicit_vr_little_endian_is_supported(self):
        from pydicom.uid import ImplicitVRLittleEndian
        r=self.load(syntax=ImplicitVRLittleEndian)
        self.assertTrue(r['series'][0]['eligible'])


if __name__=='__main__':unittest.main()
