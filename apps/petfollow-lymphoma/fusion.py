"""Resample a PET plane onto a CT plane using DICOM patient coordinates."""

import numpy as np

from geometry import ImageGeometry


def pet_on_ct(study, ct_index):
    pet_headers, ct_headers = study.pet_headers, study.ct_headers
    pet_frame = str(pet_headers[0].get("FrameOfReferenceUID", ""))
    ct_frame = str(ct_headers[0].get("FrameOfReferenceUID", ""))
    if not pet_frame or pet_frame != ct_frame:
        raise ValueError("PET/CT 缺少一致的 Frame of Reference，不能融合叠加")
    pet = ImageGeometry.from_headers(pet_headers)
    ct = ImageGeometry.from_headers(ct_headers)
    if np.asarray(pet.normal) @ np.asarray(ct.normal) < 0.999:
        raise ValueError("PET/CT 切片方向不一致，不能融合叠加")
    if not 0 <= ct_index < len(study.ct):
        raise ValueError("CT 切片超出范围")

    ct_origin = np.asarray(ct.origins[ct_index])
    pet_index = pet.nearest_index(ct_origin)
    pet_origin = np.asarray(pet.origins[pet_index])
    if abs(np.dot(ct_origin - pet_origin, pet.normal)) > max(5.0, float(ct_headers[ct_index].get("SliceThickness", 0))):
        raise ValueError("PET/CT 该层空间距离过大，不能融合叠加")
    y, x = np.indices((ct.rows, ct.columns), dtype=float)
    points = (ct_origin + x[..., None] * ct.spacing[1] * ct.row
              + y[..., None] * ct.spacing[0] * ct.column)
    offset = points - pet_origin
    px = np.sum(offset * pet.row, axis=2) / pet.spacing[1]
    py = np.sum(offset * pet.column, axis=2) / pet.spacing[0]
    valid = (px >= 0) & (py >= 0) & (px <= pet.columns - 1) & (py <= pet.rows - 1)
    x0 = np.floor(np.clip(px, 0, pet.columns - 1)).astype(int)
    y0 = np.floor(np.clip(py, 0, pet.rows - 1)).astype(int)
    x1 = np.minimum(x0 + 1, pet.columns - 1)
    y1 = np.minimum(y0 + 1, pet.rows - 1)
    fx, fy = np.clip(px - x0, 0, 1), np.clip(py - y0, 0, 1)
    source = np.asarray(study.pet[pet_index], dtype=float)
    sampled = ((1 - fy) * ((1 - fx) * source[y0, x0] + fx * source[y0, x1])
               + fy * ((1 - fx) * source[y1, x0] + fx * source[y1, x1]))
    sampled[~valid] = 0
    return sampled, valid, pet_index
