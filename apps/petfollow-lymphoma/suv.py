"""Single-slice SUVbw from rescaled classic PET pixels.

DICOM PS3.3 C.8.9.1, C.8.9.2 and C.8.9.4 define the units and reference times.
The body-weight equation follows QIBA FDG-PET's vendor-neutral SUV pseudocode
(2018-06-26). This prototype requires explicit dates and a common acquisition
start for START correction.
"""
from datetime import datetime
import math
import re

import numpy as np

from imaging import Study


def _one(values, reason):
    """A series-wide parameter must be independently supplied on every instance."""
    values = set(values)
    if len(values) != 1:
        raise ValueError(reason)
    return values.pop()


def _positive(ds, field, label):
    try:
        value = float(ds.get(field))
        if math.isfinite(value) and value > 0:
            return value
    except (TypeError, ValueError, OverflowError):
        pass
    raise ValueError(f"{label}缺失或无效")


def _datetime(raw, offset, label):
    # pydicom accepts partial DTs. Quantitation requires an unambiguous instant;
    # offsets in the DT itself take precedence over the instance's default.
    match = re.fullmatch(r"(\d{14})(\.\d{1,6})?([+-]\d{4})?", str(raw or ""))
    if match:
        clock, fraction, zone = match.groups()
        zone = zone or str(offset or "")
        try:
            return datetime.strptime(clock + (fraction or "") + zone,
                                     "%Y%m%d%H%M%S" + (".%f" if fraction else "") + ("%z" if zone else ""))
        except ValueError:
            pass
    raise ValueError(f"{label}日期、时间或时区缺失或无效")


def _acquisition(ds):
    offset = ds.get("TimezoneOffsetFromUTC")
    date, time = ds.get("AcquisitionDate"), ds.get("AcquisitionTime")
    candidates = []
    if ds.get("AcquisitionDateTime"):
        candidates.append(_datetime(ds.AcquisitionDateTime, offset, "PET 采集开始"))
    if date or time:
        candidates.append(_datetime(str(date or "") + str(time or ""), offset, "PET 采集开始"))
    return _one(candidates, "PET 采集开始时间缺失或矛盾")


def _scale(headers):
    units = _one((str(ds.get("Units", "")) for ds in headers), "PET 层间定量单位不一致")
    if units not in ("BQML", "GML"):
        raise ValueError("PET 单位缺失或不支持 SUVbw 换算")
    decay = _one((str(ds.get("DecayCorrection", "")) for ds in headers), "PET 层间衰变校正参考不一致")
    for ds in headers:
        codes = ds.get("CorrectedImage", [])
        if "DECY" not in ([codes] if isinstance(codes, str) else codes or []):
            raise ValueError("缺少放射性衰变校正标记 DECY")
        # Viewing can use unscaled pixels. Quantitation requires an actual
        # linear calibration. The importer has already applied it per plane.
        if ("RescaleIntercept" not in ds or "ModalityLUTSequence" in ds
                or not math.isfinite(float(ds.RescaleIntercept))):
            raise ValueError("PET 线性像素标定缺失或无效")
        _positive(ds, "RescaleSlope", "PET 像素换算斜率")
    if units == "GML":
        if any(ds.get("SUVType", "BW") != "BW" for ds in headers):
            raise ValueError("GML 的 SUV 类型不明确或非体重法")
        if decay not in ("", "START", "ADMIN"):
            raise ValueError("直接 SUVbw 的衰变校正标记矛盾或不受支持")
        return 1.0, "DICOM 直接 SUVbw（GML）"

    if decay not in ("START", "ADMIN"):
        raise ValueError("BQML 缺少可用的衰变校正参考（START / ADMIN）")
    if any(ds.get("SUVType", "BW") != "BW" for ds in headers):
        raise ValueError("BQML 与定量类型标记矛盾")
    weight = _one((_positive(ds, "PatientWeight", "体重") for ds in headers), "PET 层间体重不一致")
    tracers = []
    for ds in headers:
        items = ds.get("RadiopharmaceuticalInformationSequence") or []
        if len(items) != 1:
            raise ValueError("注射记录缺失或包含多次注射")
        tracers.append(items[0])
    _one((str(drug.get("RadiopharmaceuticalAdministrationEventUID", "")) for drug in tracers),
         "PET 层间注射记录不一致")
    if decay == "ADMIN":
        _one(((str(drug.get("RadiopharmaceuticalStartDateTime", "")),
               str(drug.get("RadiopharmaceuticalStartTime", ""))) for drug in tracers),
             "PET 层间注射时间不一致")
    dose = _one((_positive(drug, "RadionuclideTotalDose", "注射剂量") for drug in tracers), "PET 层间注射剂量不一致")
    if decay == "START":
        half_life = _one((_positive(drug, "RadionuclideHalfLife", "核素半衰期") for drug in tracers),
                         "PET 层间核素半衰期不一致")
        # Later bed positions have their own acquisition times. Without a
        # single established reference we cannot use the ROI slice's clock.
        start = _one((_acquisition(ds) for ds in headers), "PET 各层采集开始时间不同，无法确认共同衰变参考")
        injection = _one((_datetime(drug.get("RadiopharmaceuticalStartDateTime"),
                                    ds.get("TimezoneOffsetFromUTC"), "注射")
                          for ds, drug in zip(headers, tracers)), "PET 层间注射时间不一致")
        if (start.tzinfo is None) != (injection.tzinfo is None):
            raise ValueError("采集与注射时区无法对齐")
        elapsed = (start - injection).total_seconds()
        if elapsed < 0:
            raise ValueError("注射时间晚于采集时间")
        dose *= 2.0 ** (-elapsed / half_life)
        if dose <= 0:
            raise ValueError("衰变换算后剂量无效")
    # Total Dose is in Bq at administration. ADMIN pixels already have that
    # reference; START pixels require the dose at the common scan start.
    return weight * 1000.0 / dose, f"BQML 体重法（{decay}）"


def _has_padding(samples, ds):
    # Padding is encoded in *stored* values. Match the importer's rescale and
    # float32 conversion before testing the selected ROI in modality units.
    if "PixelPaddingValue" not in ds:
        return "PixelPaddingRangeLimit" in ds
    first = ds.PixelPaddingValue
    bounds = np.array([first, ds.get("PixelPaddingRangeLimit", first)], dtype=float)
    if not np.isfinite(bounds).all():
        return True
    bounds = (bounds * float(ds.RescaleSlope) + float(ds.RescaleIntercept)).astype(np.float32)
    return np.any((samples >= bounds.min()) & (samples <= bounds.max()))


def suv_for_roi(study: Study, mask: np.ndarray, slice_index: int, *, headers=None) -> tuple[float | None, str]:
    if study.exam.get("attenuation_corrected") is not True:
        return None, "缺/未衰减校正，SUV 仅供复核"
    if (isinstance(slice_index, (bool, np.bool_)) or not isinstance(slice_index, (int, np.integer))
            or not 0 <= slice_index < len(study.pet) or len(study.pet_headers) != len(study.pet)):
        return None, "ROI 层面与 PET 序列不匹配"
    mask = np.asarray(mask)
    if mask.dtype != np.bool_ or mask.shape not in (study.pet.shape[1:], study.pet.shape) or not mask.any():
        return None, "PET ROI 为空或与层面不匹配"
    try:
        scale, method = _scale(headers if headers is not None else study.pet_headers)
        if headers is not None:
            method += " [Manual Input]"
        if mask.ndim == 2:
            samples = study.pet[slice_index][mask]
            if _has_padding(samples, study.pet_headers[slice_index]):
                return None, "PET ROI 涉及像素填充值，请复核轮廓"
        else:
            selected = []
            for index in np.flatnonzero(mask.any(axis=(1, 2))):
                part = study.pet[index][mask[index]]
                if _has_padding(part, study.pet_headers[index]):
                    return None, "PET ROI 涉及像素填充值，请复核轮廓"
                selected.append(part)
            samples = np.concatenate(selected)
    except ValueError as exc:
        return None, str(exc)
    except (TypeError, OverflowError):
        return None, "PET 定量参数无效"
    result = float(samples.max()) * scale
    if not math.isfinite(result) or result < 0:
        return None, "ROI 内 SUVmax 无效"
    return result, method
