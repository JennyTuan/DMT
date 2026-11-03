"""Double-source, auditable replacement of missing BQML SUV metadata only."""

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from roi_store import _safe_id, _write_json
from suv import _datetime, _scale


FIELDS = {"patient_weight_kg", "dose_bq", "half_life_s", "injection_datetime", "acquisition_datetime"}
NUMERIC = {"patient_weight_kg", "dose_bq", "half_life_s"}


def read_manual(root, exam_id):
    path = Path(root) / "data" / "manual_params" / (_safe_id(exam_id) + ".json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if payload.get("schema_version") != 1 or payload.get("exam_id") != exam_id:
        raise ValueError("人工定量参数与检查不一致")
    latest = payload["versions"][-1] if payload.get("versions") else None
    return None if latest and latest.get("revoked") else latest


def effective_headers(headers, record):
    if record is None:
        return headers
    if not headers or {str(ds.get("Units", "")) for ds in headers} != {"BQML"}:
        raise ValueError("人工补录仅支持原始单位为 BQML 的 PET 序列")
    values = record["values"]
    copies = deepcopy(headers)
    for ds in copies:
        def fill(target, name, value):
            existing = target.get(name)
            if existing is not None and str(existing).strip():
                if name in ("PatientWeight", "RadionuclideTotalDose", "RadionuclideHalfLife"):
                    if not math.isclose(float(existing), float(value), rel_tol=1e-4):
                        raise ValueError(f"人工补录与 DICOM {name} 冲突")
                elif str(existing) != str(value):
                    raise ValueError(f"人工补录与 DICOM {name} 冲突")
            else:
                setattr(target, name, value)

        if "patient_weight_kg" in values:
            fill(ds, "PatientWeight", values["patient_weight_kg"])
        if "acquisition_datetime" in values:
            fill(ds, "AcquisitionDateTime", values["acquisition_datetime"])
        if any(key in values for key in ("dose_bq", "half_life_s", "injection_datetime")):
            items = ds.get("RadiopharmaceuticalInformationSequence")
            if not items:
                ds.RadiopharmaceuticalInformationSequence = Sequence([Dataset()])
                items = ds.RadiopharmaceuticalInformationSequence
            if len(items) != 1:
                raise ValueError("DICOM 注射记录多于一次，不能人工补录")
            drug = items[0]
            for key, name in (("dose_bq", "RadionuclideTotalDose"),
                              ("half_life_s", "RadionuclideHalfLife"),
                              ("injection_datetime", "RadiopharmaceuticalStartDateTime")):
                if key in values:
                    fill(drug, name, values[key])
    return tuple(copies)


def save_manual(root, exam_id, headers, source_a, source_b, reviewer):
    try:
        _scale(headers)
    except ValueError:
        pass
    else:
        raise ValueError("原始 DICOM 定量参数完整，无需人工补录")
    reviewer = str(reviewer).strip()
    if not reviewer:
        raise ValueError("人工补录需填写核对人")
    if not isinstance(source_a, dict) or not isinstance(source_b, dict):
        raise ValueError("人工补录需要两份来源记录")
    name_a, name_b = str(source_a.get("name", "")).strip(), str(source_b.get("name", "")).strip()
    values_a, values_b = source_a.get("values"), source_b.get("values")
    if not name_a or not name_b or name_a == name_b:
        raise ValueError("请填写两个不同的参数来源")
    if (not isinstance(values_a, dict) or not values_a or values_a != values_b
            or any(key not in FIELDS for key in values_a)):
        raise ValueError("两份来源的补录字段及数值必须一致")
    normalized = {}
    for key, raw in values_a.items():
        if key in NUMERIC:
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{key} 必须为正数") from None
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} 必须为正数")
            normalized[key] = value
        else:
            value = str(raw).strip()
            _datetime(value, None, "人工补录时间")
            normalized[key] = value
    record = {"values": normalized, "source_a": name_a, "source_b": name_b,
              "reviewer": reviewer, "confirmed_at": datetime.now(timezone.utc).isoformat(),
              "watermark": "[Manual Input]"}
    _scale(effective_headers(headers, record))
    path = Path(root) / "data" / "manual_params" / (_safe_id(exam_id) + ".json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {"schema_version": 1, "exam_id": exam_id, "versions": []}
    if payload.get("exam_id") != exam_id or payload.get("schema_version") != 1:
        raise ValueError("既有人工参数记录与检查不一致")
    record["version"] = len(payload["versions"]) + 1
    payload["versions"].append(record)
    _write_json(path, payload)
    return record


def revoke_manual(root, exam_id, reviewer, reason):
    reviewer, reason = str(reviewer).strip(), str(reason).strip()
    if not reviewer or not reason:
        raise ValueError("撤销补录需填写核对人和原因")
    current = read_manual(root, exam_id)
    if current is None:
        raise ValueError("当前没有可撤销的人工参数")
    path = Path(root) / "data" / "manual_params" / (_safe_id(exam_id) + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    event = {"version": len(payload["versions"]) + 1, "revoked": True,
             "reviewer": reviewer, "reason": reason,
             "confirmed_at": datetime.now(timezone.utc).isoformat()}
    payload["versions"].append(event)
    _write_json(path, payload)
    return event
