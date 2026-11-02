"""Local, read-only Pack 05 rules for measurements, prior links and report text."""

import re
import unicodedata
from collections import Counter
from datetime import datetime
from math import isfinite


BANNER = "原型·不可用于临床诊疗决策"
_NO_ATTENUATION = "缺/未衰减校正，SUV 仅供复核"

# Keep the output vocabulary here so checking a bundle requires no files or services.
# ASCII boundaries work next to Chinese text and protect acronyms embedded in IDs.
_EXCLUDED = re.compile(
    r"deauville|lugano"
    r"|(?<![a-z0-9_])(?:response|[应應]答|[疗療]效)\s*[:=]?\s*(?:cr|pr|sd|pd)(?![a-z0-9_])"
    r"|(?<![a-z0-9_])(?:cmr|pmr|nmr|pmd|smd|remission|benign|malignan(?:t|cy)"
    r"|(?:complete|partial|no)\s+(?:metabolic\s+)?response|metabolic\s+response"
    r"|(?:progressive|stable)\s+(?:metabolic\s+)?disease|disease\s+progression"
    r"|treatment\s+(?:response|efficacy)|(?:assisted|automated|auxiliary)\s+diagnosis"
    r"|diagnostic\s+conclusion)(?![a-z0-9_])"
    r"|[缓緩]解|[恶惡]性|良性|[辅輔]助[诊診][断斷]|[诊診][断斷][结結][论論]"
    r"|[疗療]效(?:[结結][论論]|[评評](?:估|价|價)|分[级級])|代[谢謝][应應]答"
    r"|(?:疾病|代[谢謝])(?:[进進]展|[稳穩]定)|[卢盧]加[诺諾]|[多杜]维尔"
)


def contains_banned_term(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    return bool(_EXCLUDED.search(normalized))


def _result(gate_id, level, target, message, action="无需处理"):
    return {"gate_id": gate_id, "level": level, "target_id": target,
            "message": message, "action": action}


def _safe_reason(reason, fallback):
    return reason if reason and not contains_banned_term(reason) else fallback


def _ac_gate(exam, target, failure_level):
    if exam.get("attenuation_corrected") is True:
        return _result("AC_MISSING", "pass", target, "检查记录已衰减校正")
    return _result("AC_MISSING", failure_level, target, _NO_ATTENUATION, "核对 PET 衰减校正来源")


def _field_gate(gate_id, target, value, error, prerequisite, name, action):
    if prerequisite:
        return _result(gate_id, "not_checked", target, prerequisite, action)
    if error or type(value) not in (float, int) or value < 0 or (isinstance(value, float) and not isfinite(value)):
        message = _safe_reason(error, f"缺少可核对的{name}结果")
        return _result(gate_id, "review", target, message, action)
    return _result(gate_id, "pass", target, f"已记录{name}，未发现该项计算失败记录")


def measurement_gates(exam: dict, measurement: dict, *, roi_valid: bool | None = None,
                      field_errors: dict | None = None, quantitative: bool = True) -> list[dict]:
    """field_errors maps each field to its current ROI's latest automatic source_error.

    Pack 03 may retain a human value after calculation fails. Never infer recovery
    from that value, discard it, or change a review state in this evaluator.
    """
    target = measurement["measurement_id"]
    ac = _ac_gate(exam, target, "review")
    errors = field_errors or {}
    suv_error = errors.get("suv_max") or ""
    diameter_error = errors.get("longest_diameter_mm") or ""

    # A Pack 03 failure before either calculator runs has the same ROI error
    # on both fields (the SUV note can also carry the AC warning).
    roi_reason = ""
    if diameter_error.startswith("ROI 量测失败") and suv_error.startswith(diameter_error):
        roi_reason = diameter_error
    elif diameter_error.startswith("ROI 与 PET 层面不匹配或为空"):
        roi_reason = diameter_error
    if not (measurement.get("roi_ref") or "").strip() or roi_valid is False or roi_reason:
        roi = _result("ROI_EMPTY", "review", target,
                      _safe_reason(roi_reason, "ROI 引用缺失、掩膜为空或来源无法核对"), "重新核对并保存轮廓")
    elif roi_valid is None:
        roi = _result("ROI_EMPTY", "not_checked", target, "已有 ROI 引用，尚未核对掩膜", "打开检查核对轮廓")
    else:
        roi = _result("ROI_EMPTY", "pass", target, "已核对非空 ROI")

    prerequisite = None
    if not quantitative:
        prerequisite = "本次仅保存轮廓，未运行量测"
    elif roi["level"] == "review":
        prerequisite = "ROI 来源待核对，无法检查该项量测"
    suv_prerequisite = prerequisite
    if ac["level"] == "review":
        # Pack 03 adds the AC note even to an otherwise successful method
        # description. Only a separate conversion failure supports both rules.
        detail = suv_error.partition(_NO_ATTENUATION)[0].strip(" 。；")
        if not detail or (_NO_ATTENUATION in suv_error and not re.search(r"缺|失|不|无|矛盾|晚于", detail)):
            suv_prerequisite = "缺少衰减校正，未单独确认 SUV 换算条件"
    suv = _field_gate("SUV_META_MISSING", target, measurement.get("suv_max"), suv_error,
                      suv_prerequisite, "SUV 换算", "核对 PET 定量单位和换算依据")
    diameter = _field_gate("CT_ALIGN_FAIL", target, measurement.get("longest_diameter_mm"), diameter_error,
                           prerequisite, "CT 最长径估计", "核对 PET 与 CT 层面及测径依据")
    results = [ac, suv, diameter, roi]
    if measurement.get("state") in ("accepted", "rejected"):
        for result in results:
            if result["level"] == "review":
                result.update(level="block", action="当前来源与既有终态不相容，请核对来源后再导出")
    return results


def eligible_prior(current_exam: dict, candidate_exam: dict) -> bool:
    """Pack 04 accepts a different, strictly earlier exam for the same patient."""
    if (not current_exam.get("patient_pseudo_id")
            or candidate_exam.get("patient_pseudo_id") != current_exam["patient_pseudo_id"]
            or not candidate_exam.get("exam_id") or candidate_exam["exam_id"] == current_exam.get("exam_id")):
        return False
    try:
        prior = datetime.fromisoformat(candidate_exam["study_datetime"])
        current = datetime.fromisoformat(current_exam["study_datetime"])
        return prior.tzinfo is not None and current.tzinfo is not None and prior < current
    except (KeyError, TypeError, ValueError):
        return False


def prior_gates(bundle: dict, prior_bundle: dict | None, *, skipped=()) -> list[dict]:
    exam = bundle["exam"]
    prior_id = exam.get("prior_exam_id")
    target = exam["exam_id"]
    candidate = (prior_bundle or {}).get("exam") or {}
    linked = bool(prior_id and prior_id == candidate.get("exam_id") and eligible_prior(exam, candidate))
    if prior_id is None:
        link = _result("PRIOR_BROKEN", "pass", target, "本次检查未设置先验")
    elif linked:
        link = _result("PRIOR_BROKEN", "pass", target, "已核对同一患者的较早检查")
    else:
        link = _result("PRIOR_BROKEN", "block", target, "关联的先验缺失，或患者、时间或标识不符",
                       "重新关联或清除先验后再导出")
    results = [link]
    if not bundle["lesions"]:
        results.append(_result("TRACK_INCOMPLETE", "not_checked", target, "本次尚无病灶可配对"))
        return results
    current_counts = Counter(row.get("lesion_track_id") for row in bundle["lesions"])
    prior_counts = Counter(row.get("lesion_track_id") for row in prior_bundle["lesions"]) if linked else {}
    skipped = set(skipped)
    for lesion in bundle["lesions"]:
        lesion_id = lesion["lesion_id"]
        track = lesion.get("lesion_track_id") or ""
        if prior_id is None:
            result = _result("TRACK_INCOMPLETE", "not_checked", lesion_id, "未设置先验，无需配对")
        elif lesion_id in skipped:
            result = _result("TRACK_INCOMPLETE", "pass", lesion_id, "已由操作者显式跳过配对")
        elif track.strip() and not linked:
            result = _result("TRACK_INCOMPLETE", "not_checked", lesion_id, "先验关联待修复，无法核对配对", "先核对先验")
        elif track.strip() and current_counts[track] == 1 and prior_counts.get(track) == 1:
            result = _result("TRACK_INCOMPLETE", "pass", lesion_id, "两次检查的跟踪号唯一匹配")
        else:
            result = _result("TRACK_INCOMPLETE", "warn", lesion_id, "病灶尚无唯一的先验配对",
                             "核对配对或显式跳过，导出时提示")
        results.append(result)
    return results


def report_gates(bundle: dict, text: str | None = None) -> list[dict]:
    exam = bundle["exam"]
    target = exam["exam_id"]
    banner_ok = exam.get("prototype_banner") == BANNER
    if text is not None:
        banner_ok = banner_ok and (text == BANNER or text.startswith((BANNER + "\n", BANNER + "\r")))
    if banner_ok:
        banner = _result("PROTOTYPE_BANNER", "pass", target, "原型声明已核对")
    else:
        banner = _result("PROTOTYPE_BANNER", "block", target, "缺少完整的原型声明",
                         "核对检查声明及导出首行后重新生成")
    if (any(contains_banned_term(lesion["label"]) for lesion in bundle["lesions"])
            or (text is not None and contains_banned_term(text))):
        terms = _result("BANNED_TERMS", "block", target, "草稿仅限描述性内容",
                        "核对病灶部位和手写描述后重新生成")
    else:
        terms = _result("BANNED_TERMS", "pass", target, "所查文本符合描述性用词要求")
    return [banner, terms]


def evaluate_bundle(bundle: dict, prior_bundle: dict | None = None, *, roi_validity=None,
                    field_errors=None, skipped=(), text: str | None = None) -> list[dict]:
    """Evaluate without changing the manifest. Optional measurement evidence is keyed by measurement_id."""
    results = []
    if not bundle["measurements"]:
        target = bundle["exam"]["exam_id"]
        results.append(_ac_gate(bundle["exam"], target, "warn"))
        for gate in ("SUV_META_MISSING", "CT_ALIGN_FAIL", "ROI_EMPTY"):
            results.append(_result(gate, "not_checked", target, "本次尚无量测可核对"))
    for measurement in bundle["measurements"]:
        target = measurement["measurement_id"]
        results.extend(measurement_gates(bundle["exam"], measurement, roi_valid=(roi_validity or {}).get(target),
                                         field_errors=(field_errors or {}).get(target)))
    results.extend(prior_gates(bundle, prior_bundle, skipped=skipped))
    results.extend(report_gates(bundle, text))
    return results
