import tempfile
import unittest
from pathlib import Path
import numpy as np
from helpers import make_ct, SOURCE


class ViewerTests(unittest.TestCase):
    def setUp(self):
        from apps.lungct.service import Service
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);make_ct(self.root/'input')
        self.service=Service(self.root/'store',allowed_roots=[self.root])
        self.project=self.service.create_project('P','OP')['project_id']
        self.series=self.service.import_study(self.project,self.root/'input',SOURCE)['series'][0]

    def test_A02_original_lps_roundtrip_and_coronal_position(self):
        from apps.lungct.viewer import coronal, image_png, locate
        from apps.lungct.geometry import patient_to_pixel
        volume,g=self.service.volume(self.project,self.series['series_key'])
        for z,x,y in [(4,20,28),(6,48,30)]:
            p=g.pixel_to_patient(z,x,y)
            i,xx,yy=patient_to_pixel(g,p)
            np.testing.assert_allclose([i,xx,yy],[z,x,y],atol=.5)
            result=locate(self.series,p)
            self.assertEqual(result['slice_key'],self.series['slice_keys'][z])
            array,meta=coronal(volume,g,p[1])
            px=round((p[0]-meta['x_min'])/meta['spacing'])
            pz=round((meta['z_max']-p[2])/meta['spacing'])
            self.assertAlmostEqual(float(array[pz,px]),float(volume[z,y,x]),delta=.01)
        self.assertTrue(image_png(volume[4],-600,1500).getvalue().startswith(b'\x89PNG'))

    def test_reversed_orientation_is_not_screen_side_guess(self):
        from apps.lungct.viewer import locate, coronal
        from apps.lungct.geometry import direction
        make_ct(self.root/'reverse',orientation=(-1,0,0,0,-1,0))
        s=self.service.import_study(self.project,self.root/'reverse',SOURCE)['series'][0]
        volume,g=self.service.volume(self.project,s['series_key'])
        self.assertIn('右',direction(g.row))
        p=g.pixel_to_patient(4,20,28);r=locate(s,p)
        self.assertEqual(r['index'],4)
        arr,m=coronal(volume,g,p[1]);x=round((p[0]-m['x_min'])/m['spacing']);z=round((m['z_max']-p[2])/m['spacing'])
        self.assertEqual(float(arr[z,x]),float(volume[4,28,20]))

    def test_http_loopback_csrf_and_no_source_path_leak(self):
        from apps.lungct.server import create_app
        app=create_app(self.service,enabled=True);client=app.test_client()
        with client.get('/') as response:self.assertEqual(response.status_code,200)
        self.assertEqual(client.get('/',headers={'Host':'evil.example'}).status_code,403)
        token=client.get('/api/session').json['token']
        self.assertEqual(client.post('/api/action',json={'action':'createProject','name':'X','operator':'R'}).status_code,403)
        self.assertEqual(client.post('/api/action',json={'action':'createProject','name':'X','operator':'R'},headers={'X-LungCT-Token':token,'Origin':'https://evil.example'}).status_code,403)
        response=client.get('/api/state',query_string={'project':self.project})
        self.assertNotIn(str(self.root).encode(),response.data)
        info=client.get('/api/series-info',query_string={'project':self.project,'series':self.series['series_key']})
        self.assertEqual(info.json,{'age':'050Y','sex':None})
        other=self.service.create_project('OTHER','OP')['project_id']
        self.assertEqual(client.get('/api/series-info',query_string={'project':other,'series':self.series['series_key']}).status_code,400)
        self.assertEqual(client.get('/api/image',query_string={'project':self.project,'series':self.series['series_key'],'index':4}).status_code,200)
        self.assertEqual(client.get('/api/image',query_string={'project':self.project,'series':self.series['series_key'],'index':99}).status_code,400)
        with self.assertRaises(ValueError):create_app(self.service,enabled=False)

    def test_raw_hu_frame_preserves_values_and_project_boundary(self):
        from apps.lungct.server import create_app
        client=create_app(self.service,enabled=True).test_client()
        series=self.series['series_key']
        query=dict(project=self.project,series=series,index=4,format='hu')
        frame=client.get('/api/image',query_string=query)
        self.assertEqual(frame.mimetype,'application/octet-stream')
        volume,g=self.service.volume(self.project,series)
        np.testing.assert_array_equal(np.frombuffer(frame.data,dtype='<f4').reshape(volume[4].shape),volume[4])
        from apps.lungct.viewer import coronal
        array,_=coronal(volume,g)
        locator=client.get('/api/image',query_string={**query,'plane':'coronal'})
        np.testing.assert_array_equal(np.frombuffer(locator.data,dtype='<f4').reshape(array.shape),array)
        other=self.service.create_project('OTHER','OP')['project_id']
        self.assertEqual(client.get('/api/image',query_string={**query,'project':other}).status_code,400)
        self.assertEqual(client.get('/api/image',query_string=query,headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)


if __name__=='__main__':unittest.main()
