"""DICOM Key Object Selection for a reviewed PET lesion and nearest CT plane."""

from io import BytesIO
from copy import deepcopy

import highdicom as hd
from pydicom.sr.coding import Code
from pydicom.uid import generate_uid

from ct_dimensions import dimensions_for_roi


def key_object_bytes(study, store, lesion_id):
    mask, meta = store.load_roi(lesion_id)
    pet_index = meta["slice_index"]
    sources = [deepcopy(study.pet_headers[pet_index])]
    dimensions, _ = dimensions_for_roi(study, mask, pet_index)
    if dimensions is not None:
        sources.append(deepcopy(study.ct_headers[dimensions["ct_index"]]))
    for ds in sources:
        for key in ("PatientID", "PatientName", "PatientBirthDate", "PatientSex",
                    "AccessionNumber", "StudyID", "StudyDate", "StudyTime"):
            if key not in ds:
                setattr(ds, key, "")
    if any(not ds.get("SOPInstanceUID") or not ds.get("SOPClassUID") for ds in sources):
        raise ValueError("Key Image 缺少原始 DICOM 实例标识")
    content = hd.ko.KeyObjectSelection(
        document_title=Code("113009", "DCM", "For Research"),
        referenced_objects=sources,
        description="Research prototype key images; verify against source DICOM.",
    )
    document = hd.ko.KeyObjectSelectionDocument(
        evidence=sources, content=content,
        series_instance_uid=generate_uid(), series_number=9001,
        sop_instance_uid=generate_uid(), instance_number=1,
        manufacturer="DMT Research Prototype",
    )
    output = BytesIO()
    document.save_as(output, enforce_file_format=True)
    return output.getvalue()
