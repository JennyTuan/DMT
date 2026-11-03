"""Orthogonal review planes from a geometrically regular classic DICOM stack."""

import numpy as np

from geometry import ImageGeometry


def reconstruct(volume, headers, plane, index=0):
    if plane not in ("coronal", "sagittal", "mip"):
        raise ValueError("重建平面无效")
    geometry = ImageGeometry.from_headers(headers)
    if volume.shape != (len(geometry.origins), geometry.rows, geometry.columns):
        raise ValueError("影像体积与 DICOM 空间几何不一致")
    if len(volume) < 2:
        raise ValueError("重建至少需要两层影像")
    locs = np.asarray(geometry.locations)
    steps = np.diff(locs)
    if (np.any(steps <= 0) or np.max(np.abs(steps - np.median(steps))) > 0.5):
        raise ValueError("切片间距不规则，不能可靠重建多平面图像")
    origins = np.asarray(geometry.origins)
    offsets = origins - origins[0]
    if (np.max(np.abs(offsets @ np.asarray(geometry.row))) > 0.5
            or np.max(np.abs(offsets @ np.asarray(geometry.column))) > 0.5):
        raise ValueError("切片间存在平面位移，不能可靠重建多平面图像")
    if plane == "mip":
        image = volume.max(axis=1)
        spacing = (float(np.median(steps)), geometry.spacing[1])
    elif plane == "coronal":
        if type(index) is not int or not 0 <= index < geometry.rows:
            raise ValueError("冠状重建位置超出范围")
        image = volume[:, index, :]
        spacing = (float(np.median(steps)), geometry.spacing[1])
    else:
        if type(index) is not int or not 0 <= index < geometry.columns:
            raise ValueError("矢状重建位置超出范围")
        image = volume[:, :, index]
        spacing = (float(np.median(steps)), geometry.spacing[0])
    return np.flipud(image), spacing
