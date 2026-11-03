"""Real-weight technical qualification outside the application case database.

This does NOT sign human intake/acceptance fields. No test adapter is imported.
All inputs must already be provisioned. Network connections are disabled here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time
import traceback
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pydicom
from PIL import Image, ImageDraw
from apps.lungct.core import digest
from apps.lungct.geometry import inspect, patient_to_pixel
from apps.lungct.model import MonaiAdapter

ROOT=Path(__file__).resolve().parents[2]
CASE=ROOT/'data/lungct-assets/nlst100206'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--profile',choices=['standard','low-memory'],default='standard')
    args=parser.parse_args()
    output=Path(args.output).resolve()
    if output.exists(): raise ValueError('Use a new output file; preserve previous attempts')
    started=time.monotonic()
    record=dict(qualification_id='qualification_'+uuid.uuid4().hex,created_at=datetime.now(timezone.utc).isoformat(),
        status='RUNNING',human_acceptance='PENDING',application_case_import='NOT_PERFORMED_PENDING_HUMAN_INTAKE',
        public_case='NLST-100206',license='CC BY 4.0',source_doi='10.7937/TCIA.HMQ8-J677',
        reference_doi='10.7937/y2dx-e334',threshold=.02,network_connections='BLOCKED_IN_PROCESS')
    try:
        import torch, monai
        record['runtime']=dict(python=platform.python_version(),torch=torch.__version__,monai=monai.__version__,
            numpy=np.__version__,cuda=torch.version.cuda,device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')
        if torch.cuda.is_available():torch.cuda.reset_peak_memory_stats()
        def deny(*args,**kwargs):raise RuntimeError('Qualification runtime must remain offline')
        socket.create_connection=deny
        socket.socket.connect=deny
        files=sorted((CASE/'intake').glob('*.dcm'))
        if len(files)!=160:raise ValueError('Expected 160 prepared source slices')
        datasets=[pydicom.dcmread(p) for p in files]
        geometry,errors,metrics=inspect(datasets)
        if errors:raise ValueError(errors)
        record['input_sha256']=digest(sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in files))
        record['slice_count']=len(files);record['geometry_qc']=metrics
        volume=np.stack([ds.pixel_array.astype(np.float32)*float(ds.RescaleSlope)+float(ds.RescaleIntercept) for ds in datasets])
        adapter=MonaiAdapter(ROOT/'data/lungct-assets/monai-0.6.9',profile=args.profile)
        record['model']=adapter.metadata()
        print('REAL_INFERENCE_START',json.dumps(record),flush=True)
        result=adapter.predict(volume,geometry,.02)
        record.update(status='SUCCEEDED',candidate_count=len(result['candidates']),result=result)
        references=json.loads((CASE/'intake-evidence.json').read_text())['reference_nodules']
        comparisons=[]
        for index,candidate in enumerate(result['candidates']):
            layer,x,y=patient_to_pixel(geometry,candidate['center_lps'])
            candidate['source_index']=layer;candidate['source_pixel']=[x,y]
            center=np.asarray(candidate['center_lps'])
            for reference in references:
                box=np.asarray(reference['box_lps'])
                comparisons.append(dict(candidate_index=index,reference_segment=reference['segment_number'],
                    center_distance_mm=float(np.linalg.norm(center-reference['center_lps'])),
                    center_inside_reference_extent=bool(np.all(center>=box[:3]) and np.all(center<=box[3:])),
                    score=candidate['score'],source_index=layer))
        matches=[item for item in comparisons if item['center_inside_reference_extent']]
        record['reference_extent_matches']=sorted(matches,key=lambda item:-item['score'])
        record['comparison_definition']='Candidate center inside one published MANUAL segment bounding extent; not a performance metric or human acceptance.'
        if matches:
            match=max(matches,key=lambda item:item['score'])
            candidate=result['candidates'][match['candidate_index']]
            reference=next(r for r in references if r['segment_number']==match['reference_segment'])
            layer=candidate['source_index']
            pixels=np.uint8(np.clip((volume[layer]+1350)/1500,0,1)*255)
            canvas=Image.new('RGB',(1024,620),'#151a21');panel=Image.fromarray(pixels).convert('RGB')
            canvas.paste(panel,(0,52));canvas.paste(panel,(512,52));draw=ImageDraw.Draw(canvas)
            draw.text((12,12),f'PUBLIC NLST-100206 / source slice {layer} / LPS / no clinical conclusion',fill='white')
            draw.text((12,31),'Left: source CT | Right: model (cyan) and published MANUAL reference extent (yellow)',fill='white')
            for item,color in [(candidate,'cyan'),(reference,'yellow')]:
                box=np.asarray(item['box_lps']);origin=np.asarray(geometry.origins[layer])
                a=box[:3]-origin;b=box[3:]-origin
                xy1=[float(a@geometry.row/geometry.spacing[1]),float(a@geometry.column/geometry.spacing[0])]
                xy2=[float(b@geometry.row/geometry.spacing[1]),float(b@geometry.column/geometry.spacing[0])]
                draw.rectangle([512+min(xy1[0],xy2[0]),52+min(xy1[1],xy2[1]),512+max(xy1[0],xy2[0]),52+max(xy1[1],xy2[1])],outline=color,width=2)
            draw.text((12,577),f"Real model score {candidate['score']:.5f}; reference segment {reference['segment_number']}; center distance {match['center_distance_mm']:.3f} mm",fill='white')
            draw.text((12,598),'Technical location comparison only. Human intake and A04 review signatures: PENDING.',fill='white')
            canvas.save(output.with_suffix('.png'))
    except Exception as error:
        record.update(status='FAILED',error_type=type(error).__name__,error=str(error))
        traceback.print_exc()
    finally:
        record['elapsed_seconds']=time.monotonic()-started
        if 'torch' in locals() and torch.cuda.is_available():
            record['cuda_peak_allocated_bytes']=torch.cuda.max_memory_allocated()
            record['cuda_peak_reserved_bytes']=torch.cuda.max_memory_reserved()
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('REAL_INFERENCE_END',record['status'],record.get('candidate_count'),record['elapsed_seconds'],flush=True)
    if record['status']!='SUCCEEDED':raise SystemExit(1)


if __name__=='__main__':main()
