"""In-plane caliper on the registered CT grid, estimated from a saved PET mask.

DICOM PS3.3 C.7.6.2.1.1 maps (column, row) to patient coordinates at pixel
centers. C.7.4.1 defines the shared frame of reference used by this projection.
"""
from numbers import Integral

import numpy as np

from imaging import _numbers


def _axes(header, label):
    axes = _numbers(header, "ImageOrientationPatient", 6, label + " 层面方向").reshape(2, 3)
    col_axis, row_axis = axes
    if (not np.allclose(np.linalg.norm(axes, axis=1), 1, atol=0.001, rtol=0)
            or abs(col_axis @ row_axis) > 0.001):
        raise ValueError(f"{label} 层面方向无效。")
    # Remove the small rounding error permitted in stored direction cosines.
    col_axis = col_axis / np.linalg.norm(col_axis)
    row_axis = row_axis - (row_axis @ col_axis) * col_axis
    return np.stack((col_axis, row_axis / np.linalg.norm(row_axis)))


def _spacing(header, label):
    # The two DICOM spacings are ordered (row, column), unlike our (x, y) indices.
    spacing = _numbers(header, "PixelSpacing", 2, label + " 像素间距")[::-1]
    if np.any(spacing <= 0):
        raise ValueError(f"{label} 像素间距无效。")
    return spacing


def _ct_projection(pet, ct_headers, mask, ct_shape):
    frame = pet.get("FrameOfReferenceUID")
    if not frame or any(ds.get("FrameOfReferenceUID") != frame for ds in ct_headers):
        raise ValueError("PET 与 CT 缺少共同空间参考系。")
    pet_origin = _numbers(pet, "ImagePositionPatient", 3, "PET 层面位置")
    pet_axes = _axes(pet, "PET")
    pet_steps = pet_axes * _spacing(pet, "PET")[:, None]
    pet_xy = np.column_stack(np.nonzero(mask)[::-1])
    roi_center = pet_origin + pet_xy.mean(axis=0) @ pet_steps

    # The importer validates that the CT stack has a single orientation.
    ct_origins = np.array([_numbers(ds, "ImagePositionPatient", 3, "CT 层面位置")
                           for ds in ct_headers])
    stack_normal = np.cross(*_axes(ct_headers[0], "CT"))
    index = int(np.argmin(np.abs((ct_origins - roi_center) @ stack_normal)))
    ct = ct_headers[index]
    ct_axes = _axes(ct, "CT")
    ct_normal = np.cross(*ct_axes)
    if np.linalg.norm(np.cross(np.cross(*pet_axes), ct_normal)) > 0.001:
        raise ValueError("PET 与 CT 层面不平行。")

    origin_delta = pet_origin - ct_origins[index]
    z_step = pet_steps @ ct_normal
    # The entire PET pixel footprint must fit within the nearest CT slab.
    z_extent = np.max(np.abs(origin_delta @ ct_normal + pet_xy @ z_step)) + abs(z_step).sum() / 2
    try:
        thickness = float(ct.get("SliceThickness"))
    except (TypeError, ValueError):
        thickness = 0
    if not np.isfinite(thickness) or thickness <= 0:
        if z_extent > 0.001:
            raise ValueError("CT 层厚缺失或无效，无法确认层面覆盖。")
    elif z_extent > thickness / 2 + 0.001:
        raise ValueError("ROI 层面超出 CT 层厚覆盖范围。")

    ct_spacing = _spacing(ct, "CT")
    transform = (ct_axes @ pet_steps.T) / ct_spacing[:, None]
    offset = (ct_axes @ origin_delta) / ct_spacing
    ct_xy = pet_xy @ transform.T + offset
    half_pixel = np.abs(transform).sum(axis=1) / 2
    lower, upper = ct_xy.min(axis=0) - half_pixel, ct_xy.max(axis=0) + half_pixel
    ct_size = np.array(ct_shape[::-1])
    if (lower < -0.5 - 1e-6).any() or (upper > ct_size - 0.5 + 1e-6).any():
        raise ValueError("ROI 投影超出 CT 视野。")

    # Inverse nearest-neighbor sampling preserves the mask's holes and shape.
    x0, y0 = np.maximum(np.ceil(lower - 1e-6).astype(int), 0)
    x1, y1 = np.minimum(np.floor(upper + 1e-6).astype(int) + 1, ct_size)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    ct_centers = np.stack((xx, yy), axis=-1)
    pet_centers = (ct_centers - offset) @ np.linalg.inv(transform).T
    px, py = np.floor(pet_centers + 0.5 + 1e-9).astype(int).transpose(2, 0, 1)
    height, width = mask.shape
    inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    projected = inside & mask[py.clip(0, height - 1), px.clip(0, width - 1)]
    return index, projected, ct_spacing


def _longest_chord(mask, spacing):
    # For any two occupied rows, their farthest pair lies at row endpoints.
    rows = np.flatnonzero(mask.any(axis=1))
    if not rows.size:
        return 0.0
    left = mask[rows].argmax(axis=1)
    right = mask.shape[1] - 1 - mask[rows, ::-1].argmax(axis=1)
    longest = 0.0
    for i, row in enumerate(rows):
        dx = np.maximum(right[i] - left[i:], right[i:] - left[i]) * spacing[0]
        dy = (rows[i:] - row) * spacing[1]
        longest = max(longest, np.hypot(dx, dy).max())
    return float(longest)


def diameter_for_roi(study, mask, slice_index: int) -> tuple[float | None, str]:
    """Return the farthest CT pixel-center distance in mm and its provenance."""
    mask = np.asarray(mask)
    if mask.ndim == 3:
        if mask.shape != study.pet.shape or mask.dtype != np.bool_ or not mask.any():
            return None, "三维 ROI 与 PET 体积不匹配或为空。"
        results = [diameter_for_roi(study, mask[index], int(index))
                   for index in np.flatnonzero(mask.any(axis=(1, 2)))]
        valid = [(value, note) for value, note in results if value is not None]
        if not valid:
            return None, results[0][1]
        value, note = max(valid, key=lambda item: item[0])
        return value, "三维 VOI 各层 CT 投影最长径；" + note
    if (mask.shape != study.pet.shape[1:] or mask.dtype != np.bool_ or not mask.any()
            or not isinstance(slice_index, Integral) or not 0 <= slice_index < len(study.pet)):
        return None, "ROI 与 PET 层面不匹配或为空，请重新核对轮廓。"
    pet_headers = getattr(study, "pet_headers", ())
    ct_headers = getattr(study, "ct_headers", ())
    if (not ct_headers or len(pet_headers) != len(study.pet)
            or len(ct_headers) != len(study.ct)):
        return None, "缺少与图像对应的 DICOM 层面信息，请重新导入原始序列。"
    try:
        index, projected, spacing = _ct_projection(pet_headers[slice_index], ct_headers,
                                                   mask, study.ct.shape[1:])
    except ValueError as exc:
        return None, f"{exc}请核对原始序列或在 CT 上手工测径。"
    value = _longest_chord(projected, spacing)
    if value == 0:
        return None, "ROI 投影覆盖不足两个 CT 像素中心，请在 CT 上手工测径。"
    return value, f"PET ROI 投影至 CT 第 {index + 1} 层，按投影内最远两个 CT 像素中心估计。"
