"""Strict local CT intake. Never expose source paths or header PHI to clients."""
from collections import defaultdict
import hashlib
from pathlib import Path
import numpy as np
import pydicom
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, ImplicitVRLittleEndian
from .core import code, key, digest
from .geometry import inspect, serialize

SOURCE_FLAGS = ('authorized', 'deidentified', 'pixels_checked', 'adult_chest', 'noncontrast')
PHI_TAGS = ('PatientName', 'PatientBirthDate', 'PatientAddress', 'PatientTelephoneNumbers',
            'OtherPatientNames', 'OtherPatientIDs', 'AccessionNumber', 'InstitutionName',
            'InstitutionAddress', 'ReferringPhysicianName', 'PerformingPhysicianName')


def scan(directory, project, source, allowed_roots):
    if set(source) != {'source_code','research_source',*SOURCE_FLAGS} or any(source.get(k) is not True for k in SOURCE_FLAGS):
        raise ValueError('来源、授权、脱敏、像素检查及成人胸部非增强确认缺失')
    code(source['source_code'])
    if source['research_source'] not in ('screening','non_screening','unknown'): raise ValueError('研究来源无效')
    directory = Path(directory).resolve()
    if not directory.is_dir() or not any(directory.is_relative_to(p) for p in allowed_roots):
        raise ValueError('输入目录不在已批准的本地目录中')
    groups = defaultdict(list); seen = {}
    for path in sorted(directory.rglob('*')):
        if not path.is_file(): continue
        path = path.resolve()
        if not path.is_relative_to(directory): raise ValueError('不允许目录外的符号链接')
        try: ds = pydicom.dcmread(path, stop_before_pixels=True)
        except pydicom.errors.InvalidDicomError:
            if path.suffix.lower() == '.dcm': raise ValueError('DICOM 文件无法解析') from None
            continue
        except Exception: raise ValueError('DICOM 读取失败，请检查文件完整性') from None
        if any(str(ds.get(tag, '') or '').strip() for tag in PHI_TAGS): raise ValueError('PHI：检测到未清除的身份字段，拒绝入库')
        if str(ds.get('PatientIdentityRemoved','')) != 'YES': raise ValueError('PHI：未登记 DICOM 去标识状态')
        if str(ds.get('BurnedInAnnotation','')).upper() == 'YES': raise ValueError('BURNED：存在像素烧录信息，拒绝入库')
        # Unknown burned-in state is allowed only after the mandatory explicit pixel inspection above.
        for attr in ('StudyInstanceUID','SeriesInstanceUID','SOPInstanceUID'):
            if not str(ds.get(attr,'')): raise ValueError('DICOM 缺少稳定 UID')
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        sop = str(ds.SOPInstanceUID)
        if sop in seen:
            if seen[sop] != checksum: raise ValueError('UID_CONFLICT：同一 UID 对应不同内容')
            continue
        seen[sop] = checksum
        groups[(str(ds.StudyInstanceUID),str(ds.SeriesInstanceUID))].append((path,ds,checksum))
    if not groups: raise ValueError('目录中没有可识别的 CT DICOM')
    results = []
    for (study_uid,series_uid), records in groups.items():
        headers = [r[1] for r in records]; first = headers[0]
        codes=[]; geometry=None; metrics={}
        if any(str(d.get('SOPClassUID','')) != str(CTImageStorage) or str(d.get('Modality','')) != 'CT' or int(d.get('NumberOfFrames',1))!=1 for d in headers): codes.append('CLASSIC_CT_ONLY')
        if any(str(d.file_meta.get('TransferSyntaxUID','')) not in (str(ExplicitVRLittleEndian),str(ImplicitVRLittleEndian)) for d in headers): codes.append('TRANSFER_SYNTAX')
        if any('LOCALIZER' in str(d.get('ImageType','')).upper() or 'SCOUT' in str(d.get('ImageType','')).upper() for d in headers): codes.append('LOCALIZER')
        if any(str(d.get('ContrastBolusAgent','')).strip() or float(d.get('ContrastBolusVolume',0) or 0)>0 for d in headers): codes.append('CONTRAST')
        try:
            if any(not 0 < float(d.get('SliceThickness',0)) <= 2.5 for d in headers): codes.append('THICKNESS')
            if any(str(d.get('AnatomicalOrientationType','BIPED'))!='BIPED' for d in headers): codes.append('ANATOMY')
            if len({str(d.get('PatientID','')) for d in headers})>1: codes.append('SUBJECT_CONFLICT')
            if len({str(d.get('FrameOfReferenceUID','')) for d in headers})>1: codes.append('FRAME_CONFLICT')
            first_orientation=np.asarray(first.ImageOrientationPatient,dtype=float)
            normal=np.cross(first_orientation[:3],first_orientation[3:])
            records.sort(key=lambda r:float(np.asarray(r[1].ImagePositionPatient,dtype=float) @ normal))
            headers=[r[1] for r in records]
            geometry, errors, metrics=inspect(headers); codes.extend(errors)
        except (AttributeError,TypeError,ValueError): codes.append('GEOMETRY')
        study_key=key('study',project,study_uid); series_key=key('series',project,study_uid,series_uid)
        slices=[key('slice',project,str(r[1].SOPInstanceUID)) for r in records]
        summary=dict(project_id=project,study_key=study_key,series_key=series_key,
                     subject_key=key('subject',project,str(first.get('PatientID','')) or study_uid),
                     slice_keys=slices,eligible=not codes,qc_codes=sorted(set(codes)),qc_metrics=metrics,
                     geometry=serialize(geometry) if geometry else None,
                     thickness_mm=float(first.get('SliceThickness',0) or 0),
                     source=dict(source),input_sha256=digest(sorted(r[2] for r in records)),
                     synthetic=source['source_code']=='SYNTHETIC')
        restricted=[dict(slice_key=k,sop_uid=str(d.SOPInstanceUID),study_uid=study_uid,series_uid=series_uid,
                         path=str(p),sha256=h) for k,(p,d,h) in zip(slices,records)]
        volume=None
        if not codes:
            try:
                planes=[]
                for p,d,_ in records:
                    if d.get('SamplesPerPixel')!=1 or d.get('PhotometricInterpretation') not in ('MONOCHROME1','MONOCHROME2'): raise ValueError()
                    if 'RescaleSlope' not in d or 'RescaleIntercept' not in d or float(d.RescaleSlope)<=0: raise ValueError()
                    values=pydicom.pixels.pixel_array(p).astype(np.float32)*float(d.RescaleSlope)+float(d.RescaleIntercept)
                    if values.shape!=(geometry.rows,geometry.columns) or not np.isfinite(values).all(): raise ValueError()
                    planes.append(values)
                volume=np.stack(planes)
            except Exception:
                summary['eligible']=False; summary['qc_codes'].append('PIXELS_OR_HU')
        results.append((summary,restricted,volume))
    return results
