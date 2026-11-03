"""Operator-positioned 3-D PET reference volumes in patient millimetres."""

import numpy as np
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


REFERENCE_SHAPES = {
    "liver": {"shape": "sphere", "radius_mm": 15.0},
    "blood_pool": {"shape": "cylinder", "radius_mm": 5.0, "half_height_mm": 10.0},
}


def sample_reference_voxels(volume, geometry, center_mm, kind):
    if kind not in REFERENCE_SHAPES:
        raise ValueError("未知生理内参类型")
    if volume.shape != (len(geometry.origins), geometry.rows, geometry.columns):
        raise ValueError("内参与 PET 体积几何不一致")
    center = np.asarray(center_mm, dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("内参中心坐标无效")
    spec = REFERENCE_SHAPES[kind]
    normal = np.asarray(geometry.normal)
    row = np.asarray(geometry.row)
    column = np.asarray(geometry.column)
    depth = spec.get("half_height_mm", spec["radius_mm"])
    locs = np.asarray(geometry.locations)
    center_loc = float(center @ normal)
    if center_loc - depth < locs.min() or center_loc + depth > locs.max():
        raise ValueError("内参 VOI 超出 PET 切片边界")

    selected = []
    for index, origin in enumerate(geometry.origins):
        displacement = center - np.asarray(origin)
        dz = float(displacement @ normal)
        if abs(dz) > depth:
            continue
        radius = (float(np.sqrt(max(0.0, spec["radius_mm"] ** 2 - dz ** 2)))
                  if kind == "liver" else spec["radius_mm"])
        x0 = float(displacement @ row) / geometry.spacing[1]
        y0 = float(displacement @ column) / geometry.spacing[0]
        rx, ry = radius / geometry.spacing[1], radius / geometry.spacing[0]
        if (x0 - rx < 0 or x0 + rx > geometry.columns - 1
                or y0 - ry < 0 or y0 + ry > geometry.rows - 1):
            raise ValueError("内参 VOI 超出 PET 图像边界，请移至组织内部")
        x_min, x_max = int(np.floor(x0 - rx)), int(np.ceil(x0 + rx))
        y_min, y_max = int(np.floor(y0 - ry)), int(np.ceil(y0 + ry))
        yy, xx = np.mgrid[y_min:y_max + 1, x_min:x_max + 1]
        transverse = ((xx - x0) * geometry.spacing[1]) ** 2 + ((yy - y0) * geometry.spacing[0]) ** 2
        mask = transverse <= radius ** 2 + 1e-6
        selected.append(volume[index, y_min:y_max + 1, x_min:x_max + 1][mask])
    if not selected or not any(len(values) for values in selected):
        raise ValueError("内参 VOI 没有覆盖 PET 像素")
    return np.concatenate(selected)


def reference_outline(geometry, center_mm, kind, index):
    """Intersection of a saved VOI with one displayed axial PET plane."""
    if kind not in REFERENCE_SHAPES or not 0 <= index < len(geometry.origins):
        return None
    center = np.asarray(center_mm, dtype=float)
    origin = np.asarray(geometry.origins[index])
    relative = center - origin
    spec = REFERENCE_SHAPES[kind]
    dz = float(relative @ np.asarray(geometry.normal))
    depth = spec.get("half_height_mm", spec["radius_mm"])
    if abs(dz) > depth:
        return None
    radius = (float(np.sqrt(max(0.0, spec["radius_mm"] ** 2 - dz ** 2)))
              if kind == "liver" else spec["radius_mm"])
    x = float(relative @ np.asarray(geometry.row)) / geometry.spacing[1]
    y = float(relative @ np.asarray(geometry.column)) / geometry.spacing[0]
    return (x, y, radius / geometry.spacing[1], radius / geometry.spacing[0])


def read_references(root, exam_id):
    path = Path(root) / "data" / "references" / f"{exam_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if payload.get("exam_id") != exam_id or payload.get("schema_version") != 1:
        raise ValueError("生理内参记录与检查不符")
    return payload.get("records", {})


def save_reference(root, exam_id, kind, record):
    if kind not in REFERENCE_SHAPES:
        raise ValueError("未知生理内参类型")
    path = Path(root) / "data" / "references" / f"{exam_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = read_references(root, exam_id)
    versions = list(records.get(kind, []))
    latest = {**record, "kind": kind, "version": len(versions) + 1,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    versions.append(latest)
    records[kind] = versions
    payload = {"schema_version": 1, "exam_id": exam_id, "records": records}
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return latest


def confirm_reference(root, exam_id, kind, version, reviewer):
    if kind not in REFERENCE_SHAPES or type(version) is not int or version < 1:
        raise ValueError("内参确认目标无效")
    reviewer = str(reviewer).strip()
    if not reviewer:
        raise ValueError("请填写内参确认人")
    path = Path(root) / "data" / "references" / f"{exam_id}.json"
    records = read_references(root, exam_id)
    versions = records.get(kind, [])
    if not versions or versions[-1]["version"] != version:
        raise ValueError("内参版本已更新，请刷新后核对")
    current = versions[-1]
    if current.get("suv_max") is None or current.get("suv_mean") is None:
        raise ValueError("内参定量尚不可用，不能确认")
    if current.get("placement_confirmed"):
        return current
    current["placement_confirmed"] = True
    current["status"] = "confirmed"
    current["confirmed_by"] = reviewer
    current["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    payload = {"schema_version": 1, "exam_id": exam_id, "records": records}
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return current
