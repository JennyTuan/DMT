"""CT in-plane long and perpendicular short diameter from a PET VOI projection.

These are proposed geometric estimates for clinician review, not manual CT
calipers. Both axes are taken from the same CT plane.
"""

import numpy as np

from diameter import _ct_projection


def _axes_for_mask(mask, spacing):
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(rows):
        raise ValueError("CT 投影为空")
    left = mask[rows].argmax(axis=1)
    right = mask.shape[1] - 1 - mask[rows, ::-1].argmax(axis=1)
    endpoints = np.concatenate((np.column_stack((left, rows)),
                                np.column_stack((right, rows))), axis=0).astype(float)
    endpoints *= np.asarray(spacing)
    delta = endpoints[:, None, :] - endpoints[None, :, :]
    lengths2 = np.sum(delta ** 2, axis=2)
    first, second = np.unravel_index(int(np.argmax(lengths2)), lengths2.shape)
    long_mm = float(np.sqrt(lengths2[first, second]))
    if long_mm <= 0:
        raise ValueError("CT 投影不足两个像素中心")
    direction = (endpoints[second] - endpoints[first]) / long_mm
    perpendicular = np.array([-direction[1], direction[0]])
    xy = np.column_stack(np.nonzero(mask)[::-1]).astype(float) * np.asarray(spacing)
    distances = xy @ perpendicular
    short_mm = float(distances.max() - distances.min())
    if short_mm <= 0:
        raise ValueError("CT 投影无法形成垂直短径")
    return long_mm, short_mm


def dimensions_for_roi(study, mask, slice_index):
    mask = np.asarray(mask)
    if mask.dtype != np.bool_ or mask.shape not in (study.pet.shape[1:], study.pet.shape) or not mask.any():
        return None, "ROI 与 PET 体积不匹配或为空"
    if len(study.pet_headers) != len(study.pet) or len(study.ct_headers) != len(study.ct):
        return None, "缺少 PET/CT DICOM 层面信息"
    indices = np.flatnonzero(mask.any(axis=(1, 2))) if mask.ndim == 3 else [slice_index]
    candidates = []
    errors = []
    for index in indices:
        plane = mask[index] if mask.ndim == 3 else mask
        try:
            ct_index, projected, spacing = _ct_projection(
                study.pet_headers[index], study.ct_headers, plane, study.ct.shape[1:])
            long_mm, short_mm = _axes_for_mask(projected, spacing)
            candidates.append({"ct_index": int(ct_index), "long_mm": long_mm,
                               "short_mm": short_mm, "spd_mm2": long_mm * short_mm})
        except ValueError as exc:
            errors.append(str(exc))
    if not candidates:
        return None, errors[0] if errors else "没有可用 CT 投影"
    best = max(candidates, key=lambda item: item["spd_mm2"])
    return best, "同一 CT 层投影双径估计；需医生在 CT 上核对"
