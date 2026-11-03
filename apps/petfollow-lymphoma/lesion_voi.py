"""Bounded, connected 3-D PET lesion proposal at a fraction of local SUVmax.

The user must place the seed on the lesion hotspot and review the result. A
30 mm physical search sphere limits accidental growth into distant uptake.
Touching that sphere is rejected rather than silently truncating the lesion.
"""

from collections import deque

import numpy as np


def grow_lesion(volume, geometry, index, x, y, fraction=0.41, radius_mm=30.0):
    if (volume.shape != (len(geometry.origins), geometry.rows, geometry.columns)
            or type(index) is not int or not 0 <= index < len(volume)
            or type(x) is not int or type(y) is not int
            or not 0 <= x < geometry.columns or not 0 <= y < geometry.rows
            or not np.isfinite(fraction) or not 0 < fraction <= 1):
        raise ValueError("三维病灶 VOI 的图像、种子点或阈值无效")
    center = np.asarray(geometry.pixel_to_patient(index, x, y))
    locs = np.asarray(geometry.locations)
    center_loc = locs[index]
    z_indices = np.flatnonzero(np.abs(locs - center_loc) <= radius_mm)
    if not len(z_indices):
        raise ValueError("PET 体积没有可用的病灶层面")
    z0, z1 = int(z_indices.min()), int(z_indices.max()) + 1
    xr = int(np.ceil(radius_mm / geometry.spacing[1]))
    yr = int(np.ceil(radius_mm / geometry.spacing[0]))
    x0, x1 = max(0, x - xr), min(geometry.columns, x + xr + 1)
    y0, y1 = max(0, y - yr), min(geometry.rows, y + yr + 1)
    values = np.asarray(volume[z0:z1, y0:y1, x0:x1], dtype=float)
    offsets = np.asarray(geometry.origins[z0:z1]) - center
    row = np.asarray(geometry.row)
    column = np.asarray(geometry.column)
    zz = (locs[z0:z1] - center_loc)[:, None, None]
    yy = (offsets @ column)[:, None, None] + (np.arange(y0, y1) * geometry.spacing[0])[None, :, None]
    xx = (offsets @ row)[:, None, None] + (np.arange(x0, x1) * geometry.spacing[1])[None, None, :]
    distance2 = zz * zz + yy * yy + xx * xx
    hotspot = (distance2 <= 6.0 ** 2) & np.isfinite(values)
    if not hotspot.any():
        raise ValueError("种子附近没有可用 PET 像素")
    hot = np.where(hotspot, values, -np.inf)
    start = tuple(int(v) for v in np.unravel_index(int(np.argmax(hot)), hot.shape))
    peak = float(values[start])
    if peak <= 0:
        raise ValueError("病灶热点必须为正的 PET 值")
    eligible = (distance2 <= radius_mm ** 2) & np.isfinite(values) & (values >= peak * fraction)
    local = np.zeros(values.shape, dtype=bool)
    queue = deque([start])
    local[start] = True
    while queue:
        zc, yc, xc = queue.popleft()
        for nz, ny, nx in ((zc - 1, yc, xc), (zc + 1, yc, xc),
                           (zc, yc - 1, xc), (zc, yc + 1, xc),
                           (zc, yc, xc - 1), (zc, yc, xc + 1)):
            if (0 <= nz < local.shape[0] and 0 <= ny < local.shape[1]
                    and 0 <= nx < local.shape[2] and eligible[nz, ny, nx] and not local[nz, ny, nx]):
                local[nz, ny, nx] = True
                queue.append((nz, ny, nx))
    if np.any(local & (distance2 >= (radius_mm - max(geometry.spacing)) ** 2)):
        raise ValueError("病灶 VOI 触及 30 mm 搜索边界，请重新选点或改用人工轮廓")
    if (local[0].any() or local[-1].any() or local[:, 0].any() or local[:, -1].any()
            or local[:, :, 0].any() or local[:, :, -1].any()):
        raise ValueError("病灶 VOI 触及采集或搜索边界，请核对完整影像")
    mask = np.zeros(volume.shape, dtype=bool)
    mask[z0:z1, y0:y1, x0:x1] = local
    maximum = np.unravel_index(int(np.argmax(np.where(mask, volume, -np.inf))), volume.shape)
    return mask, {"threshold_raw": peak * fraction, "maximum_raw": float(volume[maximum]),
                  "maximum_index": [int(v) for v in maximum],
                  "maximum_mm": geometry.pixel_to_patient(int(maximum[0]), int(maximum[2]), int(maximum[1])),
                  "voxel_count": int(mask.sum())}
