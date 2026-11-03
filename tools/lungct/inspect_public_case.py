"""Prepare an isolated intake copy and evidence; never assert human approval.

The licensed original files remain unchanged. Pixel data and spatial UIDs are
preserved. Reference masks are read ONLY for an external location comparison.
"""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pydicom
from PIL import Image, ImageDraw
from apps.lungct.dicom_io import PHI_TAGS
from apps.lungct.geometry import inspect, serialize

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT/'data/lungct-assets/nlst100206'


def main():
    files = list((CASE/'original').glob('*.dcm'))
    if len(files) != 160: raise ValueError('Download all 160 source slices first')
    pairs = [(p, pydicom.dcmread(p)) for p in files]
    pairs.sort(key=lambda pair: float(pair[1].ImagePositionPatient[2]))
    geometry, errors, metrics = inspect([d for p, d in pairs])
    if errors: raise ValueError(errors)
    directory = CASE/'intake'; directory.mkdir(exist_ok=True)
    audit=[]; pixels=[]
    for i, (path, ds) in enumerate(pairs):
        original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        pixel_hash=hashlib.sha256(ds.PixelData).hexdigest()
        removed=[]
        for tag in PHI_TAGS:
            if tag in ds:
                if str(ds.get(tag, '') or '').strip(): removed.append(tag)
                delattr(ds, tag)
        ds.remove_private_tags()
        # PN fields can be nested; strip them in the intake copy only.
        for element in ds.iterall():
            if element.VR == 'PN': element.value = ''
        target = directory / f'{i:04d}.dcm'
        ds.save_as(target, enforce_file_format=True)
        check=pydicom.dcmread(target)
        assert hashlib.sha256(check.PixelData).hexdigest()==pixel_hash
        assert hashlib.sha256(path.read_bytes()).hexdigest()==original_hash
        audit.append(dict(index=i, original_sha256=original_hash,
            intake_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            pixel_sha256=pixel_hash, removed_fields=removed))
        hu=ds.pixel_array.astype(np.float32)*float(ds.RescaleSlope)+float(ds.RescaleIntercept)
        pixels.append(np.uint8(np.clip((hu+1350)/1500,0,1)*255))
    for start in range(0, len(pixels), 40):
        sheet=Image.new('RGB',(8*256,5*280),'#14171b');draw=ImageDraw.Draw(sheet)
        for local,plane in enumerate(pixels[start:start+40]):
            x=(local%8)*256; y=(local//8)*280
            sheet.paste(Image.fromarray(plane).resize((256,256)),(x,y))
            draw.text((x+4,y+259),f'Source slice {start+local:03d}',fill='white')
        sheet.save(CASE/f'pixels-{start:03d}.png')
    reference=pydicom.dcmread(next((CASE/'reference').glob('*.dcm')))
    assert str(reference.ReferencedSeriesSequence[0].SeriesInstanceUID)==str(pairs[0][1].SeriesInstanceUID)
    shared=reference.SharedFunctionalGroupsSequence[0]
    orient=np.asarray(shared.PlaneOrientationSequence[0].ImageOrientationPatient,float)
    spacing=np.asarray(shared.PixelMeasuresSequence[0].PixelSpacing,float)
    masks=reference.pixel_array; references=[]
    for segment in reference.SegmentSequence:
        if segment.SegmentAlgorithmType != 'MANUAL': continue
        number=int(segment.SegmentNumber); points=[]
        for frame, group in zip(masks, reference.PerFrameFunctionalGroupsSequence):
            if int(group.SegmentIdentificationSequence[0].ReferencedSegmentNumber)!=number:continue
            ys,xs=np.where(frame>0)
            if not len(xs):continue
            origin=np.asarray(group.PlanePositionSequence[0].ImagePositionPatient,float)
            points.append(origin+xs[:,None]*orient[:3]*spacing[1]+ys[:,None]*orient[3:]*spacing[0])
        if not points:continue
        points=np.concatenate(points)
        references.append(dict(segment_number=number,label=str(segment.SegmentLabel),
            algorithm_type=str(segment.SegmentAlgorithmType),center_lps=points.mean(0).tolist(),
            box_lps=np.r_[points.min(0),points.max(0)].tolist(),voxel_count=len(points)))
    facts=dict(public_case='NLST-100206',slice_count=len(pairs),thickness_mm=float(pairs[0][1].SliceThickness),
        geometry=serialize(geometry),qc_metrics=metrics,
        contrast_agent_values=sorted({str(d.get('ContrastBolusAgent','')) for p,d in pairs}),
        burned_in_values=sorted({str(d.get('BurnedInAnnotation','')) for p,d in pairs}),
        identity_removed_values=sorted({str(d.get('PatientIdentityRemoved','')) for p,d in pairs}),
        human_acceptance='PENDING',pixel_visual_review='PENDING',reference_nodules=references,audit=audit)
    (CASE/'intake-evidence.json').write_text(json.dumps(facts,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in facts.items() if k not in ('geometry','audit')},indent=2))


if __name__=='__main__': main()
