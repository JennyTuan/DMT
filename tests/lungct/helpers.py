"""Synthetic-only, deterministic physical geometry; never clinical validation."""
from pathlib import Path
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


SOURCE = dict(source_code='SYNTHETIC', authorized=True, deidentified=True,
              pixels_checked=True, adult_chest=True, noncontrast=True,
              research_source='unknown')


def make_ct(folder, *, study=None, series=None, count=9, spacing=(0.75, 0.5),
            positions=None, orientation=(1, 0, 0, 0, 1, 0), localizer=False,
            name='', burned='NO', syntax=ExplicitVRLittleEndian):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    study, series = study or generate_uid(), series or generate_uid()
    for z in range(count):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = syntax; meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(None, {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID = CTImageStorage; ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study; ds.SeriesInstanceUID = series
        ds.PatientID = 'SYNTHETIC-SUBJECT'; ds.PatientName = name
        ds.PatientIdentityRemoved = 'YES'; ds.BurnedInAnnotation = burned
        ds.Modality = 'CT'; ds.BodyPartExamined = 'CHEST'; ds.PatientAge = '050Y'
        ds.ImageType = ['ORIGINAL', 'PRIMARY', 'LOCALIZER' if localizer else 'AXIAL']
        ds.ImagePositionPatient = [-16, -24, positions[z] if positions else z * 1.5]
        ds.ImageOrientationPatient = list(orientation); ds.PixelSpacing = list(spacing)
        ds.SliceThickness = 1.5; ds.InstanceNumber = count-z
        ds.Rows = 64; ds.Columns = 64; ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'; ds.BitsAllocated = 16
        ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = 1
        ds.RescaleSlope = 1; ds.RescaleIntercept = -1024
        pixels = np.full((64,64), 100, dtype=np.int16)
        yy,xx = np.mgrid[:64,:64]
        pixels[(xx-22)**2/220+(yy-32)**2/500<1] = 400
        pixels[(xx-44)**2/180+(yy-32)**2/500<1] = 400
        pixels[(xx-20)**2+(yy-28)**2+(z-4)**2*4<25] = 1100
        ds.PixelData = pixels.tobytes()
        ds.save_as(folder / f'{count-z:03d}.dcm', enforce_file_format=True)
    return study, series
