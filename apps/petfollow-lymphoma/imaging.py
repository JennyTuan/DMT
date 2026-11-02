"""Import one classic single-frame PET/CT pair for independent 2-D viewing."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut, pixel_array
from pydicom.uid import CTImageStorage, PositronEmissionTomographyImageStorage
from pydicom.valuerep import DA, TM


@dataclass
class Study:
    exam: dict
    pet: np.ndarray
    ct: np.ndarray
    pet_uids: list[str]
    correction_label: str
    pet_spacing: tuple[float, float]
    ct_spacing: tuple[float, float]
    pet_inverted: bool
    ct_inverted: bool
    # In-memory headers only, in exactly the same order as their decoded planes.
    pet_headers: tuple[pydicom.Dataset, ...] = field(default=(), repr=False)
    ct_headers: tuple[pydicom.Dataset, ...] = field(default=(), repr=False)


def _reference(kind, *values):
    digest = sha256("\0".join([kind, *values]).encode("utf-8")).hexdigest()
    return f"{kind}_{digest[:32]}"


def _common(headers, key, conflict):
    values = {str(ds.get(key, "") or "").strip() for ds in headers}
    values.discard("")
    if len(values) > 1:
        raise ValueError(conflict)
    return next(iter(values), "")


def _study_time(headers):
    date = _common(headers, "StudyDate", "检查日期不一致。")
    time = _common(headers, "StudyTime", "检查时间不一致。")
    offset = _common(headers, "TimezoneOffsetFromUTC", "检查时区不一致。")
    if not date or not time:
        raise ValueError("缺少检查日期或时间，请核实后重新导出序列。")
    try:
        value = datetime.combine(DA(date), TM(time))
        if offset:
            if not re.fullmatch(r"[+-]\d{4}", offset):
                raise ValueError
            value = value.replace(tzinfo=datetime.strptime(offset, "%z").tzinfo)
        else:
            # DICOM DA/TM without an offset are local wall time. The local
            # workstation's historical offset is the documented import default.
            value = value.astimezone()
        return value.isoformat()
    except (OverflowError, TypeError, ValueError, OSError):
        raise ValueError("检查日期、时间或时区无效，请核实后重新导出。") from None


def _corrected(ds):
    explicit = str(ds.get("AttenuationCorrected", "")).strip().upper()
    codes = ds.get("CorrectedImage", [])
    if isinstance(codes, str):
        codes = [codes]
    codes = {str(code).strip().upper() for code in codes or []} - {""}
    flags = set()
    if explicit in {"YES", "NO"}:
        flags.add(explicit == "YES")
    if "NONE" in codes and len(codes) > 1:
        return None
    if "ATTN" in codes:
        flags.add(True)
    elif codes and codes <= {
        "DECY", "SCAT", "DTIM", "MOTN", "PMOT", "NORM", "RAN", "RADL", "DCAL", "CLN", "NONE",
    }:
        flags.add(False)
    return flags.pop() if len(flags) == 1 else None


def _numbers(ds, key, count, label):
    try:
        array = np.asarray(ds.get(key), dtype=float)
        if array.shape == (count,) and np.isfinite(array).all():
            return array
    except (TypeError, ValueError):
        pass
    raise ValueError(f"{label}缺失或无效。")


def _ordered(planes):
    headers = [ds for _, ds in planes]
    _common(headers, "FrameOfReferenceUID", "同一序列含不同空间参考系。")
    _common(headers, "TemporalPositionIdentifier", "序列内含多个采集时相，请单独选择一个时相。")
    if any("ImagePositionPatient" in ds or "ImageOrientationPatient" in ds for ds in headers):
        orientation = _numbers(headers[0], "ImageOrientationPatient", 6, "切片方向")
        row, col = orientation[:3], orientation[3:]
        if (not np.allclose([np.linalg.norm(row), np.linalg.norm(col)], 1, atol=0.001)
                or abs(row @ col) > 0.001):
            raise ValueError("切片方向无效。")
        normal = np.cross(row, col)
        locations = []
        for ds in headers:
            if not np.allclose(_numbers(ds, "ImageOrientationPatient", 6, "切片方向"),
                               orientation, atol=0.0001, rtol=0):
                raise ValueError("序列内切片方向不一致，请单独选择一个断层序列。")
            locations.append(float(_numbers(ds, "ImagePositionPatient", 3, "切片位置") @ normal))
        if np.any(np.diff(np.sort(locations)) < 0.001):
            raise ValueError("序列内切片位置重复，请选择单个采集时相或重建序列。")
    else:
        try:
            locations = [int(ds.InstanceNumber) for ds in headers]
        except (AttributeError, TypeError, ValueError):
            raise ValueError("切片缺少空间位置及可用序号。") from None
        if len(set(locations)) != len(locations):
            raise ValueError("缺少切片位置且序号重复，无法排序。")
    return [planes[i] for i in np.argsort(locations)]


def _volume(planes, sop_class):
    planes = _ordered(planes)
    first = planes[0][1]
    spacing = _numbers(first, "PixelSpacing", 2, "像素间距")
    if np.any(spacing <= 0):
        raise ValueError("像素间距必须为正。")
    try:
        shape = (int(first.Rows), int(first.Columns))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("图像尺寸缺失或无效。") from None
    if min(shape) < 1:
        raise ValueError("图像尺寸无效。")
    photo = first.get("PhotometricInterpretation")
    volume = np.empty((len(planes), *shape), dtype=np.float32)
    for i, (path, ds) in enumerate(planes):
        if ds.get("SOPClassUID") != sop_class or ds.get("NumberOfFrames", 1) != 1:
            raise ValueError("仅支持经典单帧 PET 和 CT 断层图像，请重新导出。")
        if (photo not in {"MONOCHROME1", "MONOCHROME2"}
                or ds.get("PhotometricInterpretation") != photo or ds.get("SamplesPerPixel") != 1):
            raise ValueError("仅支持同一序列灰阶方向一致的单通道图像。")
        if (not np.allclose(_numbers(ds, "PixelSpacing", 2, "像素间距"), spacing)
                or (ds.get("Rows"), ds.get("Columns")) != shape):
            raise ValueError("同一序列的像素间距或图像尺寸不一致。")
        try:
            pixels = pixel_array(path)
        except Exception:
            raise ValueError("无法解码像素，请检查文件完整性，或重新导出未压缩 DICOM。") from None
        if pixels.shape != shape:
            raise ValueError("像素数组尺寸与单帧图像不一致。")
        try:
            if ("RescaleSlope" in ds) != ("RescaleIntercept" in ds) or ds.get("RescaleSlope") == 0:
                raise ValueError
            volume[i] = apply_modality_lut(pixels, ds)
            if not np.isfinite(volume[i]).all():
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError("像素灰阶换算参数无效。") from None
    refs = [_reference("sop", str(ds.SOPInstanceUID)) for _, ds in planes]
    headers = tuple(ds for _, ds in planes)
    return volume, refs, tuple(map(float, spacing)), photo == "MONOCHROME1", headers


def load_study(directory: Path) -> Study:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("请选择包含同次 PET 和 CT 的本地目录。")
    series = defaultdict(list)
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except InvalidDicomError:
            if path.suffix.lower() == ".dcm":
                raise ValueError("目录中有无法识别的 DICOM 文件，请检查导出是否完整。") from None
            continue
        except (OSError, ValueError, EOFError):
            raise ValueError("读取 DICOM 文件失败，请检查目录访问权限和文件完整性。") from None
        modality = str(ds.get("Modality", "")).upper()
        if modality in {"PT", "PET", "CT"}:
            series["CT" if modality == "CT" else "PET"].append((path, ds))

    planes = [plane for group in series.values() for plane in group]
    headers = [ds for _, ds in planes]
    for key in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"):
        if any(not ds.get(key) for ds in headers):
            raise ValueError("DICOM 缺少检查、序列或实例标识。")
    study_uid = _common(headers, "StudyInstanceUID", "目录中含多次检查，请仅选择同次检查的一对 PET 和 CT。")
    if not series["PET"] or not series["CT"]:
        raise ValueError("需要同次检查的 PET 和 CT 各一个序列。")
    patient_id = _common(headers, "PatientID", "目录中存在不同患者标识，不能合并。")
    issuer = _common(headers, "IssuerOfPatientID", "目录中存在不同患者标识机构，不能合并。")
    _common(headers, "PatientName", "患者资料不一致，不能合并。")
    _common(headers, "PatientBirthDate", "患者资料不一致，不能合并。")
    refs = {}
    for modality in ("PET", "CT"):
        uid = _common([ds for _, ds in series[modality]], "SeriesInstanceUID",
                      f"目录中含多个 {modality} 序列，请仅选择所需的一对 PET 和 CT。")
        refs[modality] = _reference("series", uid)
    if refs["PET"] == refs["CT"]:
        raise ValueError("PET 与 CT 的序列标识重复。")
    if len({ds.SOPInstanceUID for ds in headers}) != len(headers):
        raise ValueError("目录中存在重复 DICOM 实例，请每个切片只保留一份。")
    corrections = {_corrected(ds) for _, ds in series["PET"]}
    correction = corrections.pop() if len(corrections) == 1 else None
    exam = {
        "exam_id": _reference("exam", study_uid),
        "patient_pseudo_id": (_reference("patient", issuer, patient_id) if patient_id
                              else _reference("anonymous", study_uid)),
        "pet_series_ref": refs["PET"],
        "ct_series_ref": refs["CT"],
        "study_datetime": _study_time(headers),
        "modality": "PET-CT",
        "attenuation_corrected": correction is True,
        "disease": "lymphoma",
        "prior_exam_id": None,
        "prototype_banner": "原型·不可用于临床诊疗决策",
        "is_synthetic": any(str(ds[0x0008001C].value) == "YES" for ds in headers if 0x0008001C in ds),
    }
    pet, pet_uids, pet_spacing, pet_inverted, pet_headers = _volume(series["PET"], PositronEmissionTomographyImageStorage)
    ct, _, ct_spacing, ct_inverted, ct_headers = _volume(series["CT"], CTImageStorage)
    label = {True: "已校正", False: "未校正", None: "未知"}[correction]
    return Study(exam, pet, ct, pet_uids, label, pet_spacing, ct_spacing, pet_inverted, ct_inverted,
                 pet_headers, ct_headers)
