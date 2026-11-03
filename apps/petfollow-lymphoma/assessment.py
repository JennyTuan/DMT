"""Human-confirmed lymphoma response worksheet with source freshness checks."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from roi_store import _safe_id, _write_json


SCORES = {"1", "2", "3", "4", "5", "X"}
CATEGORIES = {"CMR", "PMR", "NMR", "PMD", "indeterminate"}


def evidence_for(state, lesion_id):
    lesion = next((item for item in state["lesions"] if item["lesion_id"] == lesion_id), None)
    measurement = next((item for item in state["measurements"] if item["lesion_id"] == lesion_id), None)
    row = next((item for item in state["rows"] if item["lesion_id"] == lesion_id), None)
    if lesion is None or measurement is None:
        raise ValueError("请选择本次检查的有效病灶")
    refs = state["references"]
    blood = refs.get("blood_pool")
    liver = refs.get("liver")
    current_suv = measurement.get("suv_max")
    suggestion = "内参或病灶 SUV 待确认，无法给出分值范围"
    if (current_suv is not None and blood and liver
            and blood.get("placement_confirmed") and liver.get("placement_confirmed")
            and blood.get("suv_mean") is not None and liver.get("suv_mean") is not None):
        if current_suv <= blood["suv_mean"]:
            suggestion = "摄取不高于纵隔血池：候选 1–2；是否无可见摄取需医生阅片"
        elif current_suv <= liver["suv_mean"]:
            suggestion = "摄取高于纵隔血池且不高于肝脏：候选 3"
        else:
            suggestion = "摄取高于肝脏：候选 4–5；程度及新病灶需医生阅片"
    evidence = {
        "exam_id": state["exam"]["exam_id"], "prior_exam_id": state["exam"].get("prior_exam_id"),
        "manual_input_version": (state["exam"].get("manual_input") or {}).get("version"),
        "lesion_id": lesion_id, "roi_ref": measurement.get("roi_ref"),
        "current_suv_max": current_suv,
        "current_diameter_mm": measurement.get("longest_diameter_mm"),
        "prior_lesion_id": row.get("prior_lesion_id") if row else None,
        "prior_suv_max": row.get("prior_suv") if row else None,
        "prior_diameter_mm": row.get("prior_mm") if row else None,
        "delta_suv_pct": row.get("delta_suv_pct") if row else None,
        "blood_pool": {"version": blood["version"], "suv_mean": blood.get("suv_mean"),
                       "confirmed": blood.get("placement_confirmed")}
        if blood else None,
        "liver": {"version": liver["version"], "suv_mean": liver.get("suv_mean"),
                  "confirmed": liver.get("placement_confirmed")}
        if liver else None,
    }
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"evidence": evidence, "fingerprint": fingerprint, "suggestion": suggestion}


def read_assessments(root, exam_id):
    path = Path(root) / "data" / "assessments" / (_safe_id(exam_id) + ".json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if payload.get("schema_version") != 1 or payload.get("exam_id") != exam_id:
        raise ValueError("医生确认记录与当前检查不一致")
    return payload.get("by_lesion", {})


def confirm_assessment(root, state, lesion_id, fingerprint, score, category, reviewer, reason):
    context = evidence_for(state, lesion_id)
    if fingerprint != context["fingerprint"]:
        raise ValueError("内参、病灶或跨期量测已更新，请重新核对后确认")
    if score not in SCORES or category not in CATEGORIES:
        raise ValueError("请选择有效的 Deauville 分值和 Lugano 分类")
    reviewer, reason = str(reviewer).strip(), str(reason).strip()
    if not reviewer or not reason:
        raise ValueError("医生确认需填写确认人和判读依据")
    exam_id = state["exam"]["exam_id"]
    records = read_assessments(root, exam_id)
    versions = records.setdefault(lesion_id, [])
    item = {"version": len(versions) + 1, "score": score, "category": category,
            "reviewer": reviewer, "reason": reason,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": fingerprint, "evidence": context["evidence"]}
    versions.append(item)
    path = Path(root) / "data" / "assessments" / (_safe_id(exam_id) + ".json")
    _write_json(path, {"schema_version": 1, "exam_id": exam_id, "by_lesion": records})
    return item
