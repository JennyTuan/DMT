"""Patient-space geometry for classic single-frame PET/CT image stacks.

DICOM Image Position (Patient), Image Orientation (Patient), and Pixel Spacing
are all required. No instance-number or proportional fallback is used here.
"""

from dataclasses import dataclass

import numpy as np


def _vector(ds, name, length):
    try:
        value = np.asarray(ds.get(name), dtype=float)
        if value.shape == (length,) and np.isfinite(value).all():
            return value
    except (TypeError, ValueError):
        pass
    raise ValueError(f"DICOM {name} 空间位置或方向缺失或无效")


@dataclass(frozen=True)
class ImageGeometry:
    origins: tuple[tuple[float, float, float], ...]
    row: tuple[float, float, float]
    column: tuple[float, float, float]
    normal: tuple[float, float, float]
    spacing: tuple[float, float]
    rows: int
    columns: int
    locations: tuple[float, ...]

    @classmethod
    def from_headers(cls, headers):
        if not headers:
            raise ValueError("DICOM 序列为空")
        first = headers[0]
        orientation = _vector(first, "ImageOrientationPatient", 6)
        row, column = orientation[:3], orientation[3:]
        if (not np.allclose([np.linalg.norm(row), np.linalg.norm(column)], 1, atol=1e-3)
                or abs(row @ column) > 1e-3):
            raise ValueError("DICOM 切片方向无效")
        normal = np.cross(row, column)
        spacing = _vector(first, "PixelSpacing", 2)
        if np.any(spacing <= 0):
            raise ValueError("DICOM 像素间距无效")
        rows, columns = int(first.Rows), int(first.Columns)
        origins = []
        for ds in headers:
            if (not np.allclose(_vector(ds, "ImageOrientationPatient", 6), orientation, atol=1e-4)
                    or not np.allclose(_vector(ds, "PixelSpacing", 2), spacing, atol=1e-4)
                    or (int(ds.Rows), int(ds.Columns)) != (rows, columns)):
                raise ValueError("DICOM 序列空间方向或间距不一致")
            origins.append(_vector(ds, "ImagePositionPatient", 3))
        locations = [float(origin @ normal) for origin in origins]
        if len(set(round(value, 4) for value in locations)) != len(locations):
            raise ValueError("DICOM 切片空间位置重复")
        return cls(tuple(tuple(map(float, point)) for point in origins),
                   tuple(map(float, row)), tuple(map(float, column)),
                   tuple(map(float, normal)), tuple(map(float, spacing)),
                   rows, columns, tuple(locations))

    def pixel_to_patient(self, index, x, y):
        if (type(index) is not int or not np.isfinite([x, y]).all()
                or not 0 <= index < len(self.origins)
                or not 0 <= x < self.columns or not 0 <= y < self.rows):
            raise ValueError("选点超出 DICOM 图像范围")
        point = (np.asarray(self.origins[index]) + np.asarray(self.row) * x * self.spacing[1]
                 + np.asarray(self.column) * y * self.spacing[0])
        return tuple(map(float, point))

    def nearest_index(self, point):
        location = float(np.asarray(point, dtype=float) @ np.asarray(self.normal))
        return int(np.argmin(np.abs(np.asarray(self.locations) - location)))


def alignment_offset(base, current, base_index, base_xy, current_index, current_xy):
    """3-D translation from two manually selected corresponding landmarks."""
    if np.asarray(base.normal) @ np.asarray(current.normal) < 0.999:
        raise ValueError("两期切片方向不一致，不能执行单点平移对齐")
    first = np.asarray(base.pixel_to_patient(base_index, *base_xy))
    second = np.asarray(current.pixel_to_patient(current_index, *current_xy))
    return tuple(map(float, second - first))
