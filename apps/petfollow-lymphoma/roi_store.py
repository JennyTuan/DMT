"""Pack 02 single-slice PET ROI creation and local versioned storage."""

import base64
import getpass
import json
import math
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from numbers import Integral, Real
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource


def _check_seed(shape, x, y, fraction):
    if len(shape) != 2 or not all(isinstance(v, Integral) for v in (x, y)):
        raise ValueError("请选择二维 PET 层面上的种子点")
    if not (0 <= x < shape[1] and 0 <= y < shape[0]):
        raise ValueError("种子点超出当前 PET 层面")
    if not isinstance(fraction, Real) or not 0 < fraction <= 1:
        raise ValueError("阈值比例必须大于 0 且不超过 100%")


def _check_slice(slice_index, sop_uid):
    if (not isinstance(slice_index, Integral) or slice_index < 0
            or not isinstance(sop_uid, str) or not sop_uid.strip()):
        raise ValueError("请指定有效的 PET 层面和实例标识")


def grow_region(plane: np.ndarray, x: int, y: int, fraction: float) -> np.ndarray:
    """Return the seed's 4-connected component at or above seed value × fraction."""
    plane = np.asarray(plane)
    _check_seed(plane.shape, x, y, fraction)
    value = float(plane[y, x])
    if not np.isfinite(value) or value <= 0:
        raise ValueError("种子点的 PET 值必须为有限正数，请另选位置")
    eligible = np.isfinite(plane) & (plane >= value * fraction)
    mask = np.zeros(plane.shape, dtype=bool)
    pending = [(x, y)]
    mask[y, x] = True
    height, width = plane.shape
    while pending:
        cx, cy = pending.pop()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < width and 0 <= ny < height and eligible[ny, nx] and not mask[ny, nx]:
                mask[ny, nx] = True
                pending.append((nx, ny))
    return mask


@lru_cache(maxsize=1)
def _bundle_validator():
    directory = Path(__file__).resolve().parents[2] / "schemas/v0"
    schemas = {path.name: json.loads(path.read_text(encoding="utf-8"))
               for path in directory.glob("*.schema.json")}
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    bundle_ref = schemas["exam.schema.json"]["$id"] + "#/$defs/bundle"
    return Draft202012Validator({"$ref": bundle_ref}, registry=registry, format_checker=FormatChecker())


def _validate_bundle(bundle):
    try:
        _bundle_validator().validate(bundle)
    except ValidationError as exc:
        raise ValueError(f"检查数据未通过 Pack 01 校验（{exc.json_path}）") from exc
    lesion_ids = {row["lesion_id"] for row in bundle["lesions"]}
    if (len(lesion_ids) != len(bundle["lesions"])
            or any(row["exam_id"] != bundle["exam"]["exam_id"] for row in bundle["lesions"])
            or any(row["lesion_id"] not in lesion_ids for row in bundle["measurements"])):
        raise ValueError("检查、病灶和量测标识不一致")


def _safe_id(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", value)
            or value.endswith(".") or re.fullmatch(r"CON|AUX|PRN|NUL|(?:COM|LPT)[0-9]",
                                                   value.split(".")[0], re.IGNORECASE)):
        raise ValueError("检查或病灶标识不能用于本地文件名")
    return value


def _local_path(root, relative):
    path = root / relative
    if path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("检查数据路径超出本地存储目录或包含链接")
    return path


@contextmanager
def _writer_lock(lock_path):
    # A stable file (never replaced/unlinked). The OS releases its lock after a crash.
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("另一窗口正在保存此检查，请稍后重新打开") from exc
        yield  # Closing the handle releases the lock on both platforms.


def _write_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    try:
        with temp:
            json.dump(content, temp, ensure_ascii=False, indent=2, allow_nan=False)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp.name, path)
    finally:
        Path(temp.name).unlink(missing_ok=True)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("本地检查或 ROI 文件无法读取，请核对数据目录") from exc


def _records(bundle, lesion_id):
    lesions = [r for r in bundle["lesions"] if r["lesion_id"] == lesion_id]
    measurements = [r for r in bundle["measurements"] if r["lesion_id"] == lesion_id]
    if len(lesions) != 1 or len(measurements) != 1:
        raise ValueError("未找到唯一匹配的病灶和量测")
    return lesions[0], measurements[0]


class StudyStore:
    def __init__(self, root: Path, exam: dict):
        initial = {"exam": deepcopy(exam), "lesions": [], "measurements": []}
        _validate_bundle(initial)
        self.root = Path(root).resolve()
        self.exam_id = _safe_id(exam["exam_id"])
        self.path = _local_path(self.root, Path("data/exams") / (self.exam_id + ".json"))
        self.lock_path = _local_path(self.root, self.path.with_suffix(".lock"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _writer_lock(self.lock_path):
            if self.path.exists():
                self.bundle = _read_json(self.path)
                _validate_bundle(self.bundle)
                identity = ("exam_id", "patient_pseudo_id", "pet_series_ref", "ct_series_ref")
                saved = self.bundle["exam"]
                if any(saved[key] != exam[key] for key in identity):
                    raise ValueError("此检查标识已对应其他患者或影像序列")
                if (saved["attenuation_corrected"] != exam["attenuation_corrected"]
                        or saved.get("is_synthetic", False) != exam.get("is_synthetic", False)
                        or saved["study_datetime"] != exam["study_datetime"]):
                    raise ValueError("检查时间、校正或示意标记与已保存记录不一致，请核对原始序列")
            else:
                _write_json(self.path, initial)
                self.bundle = initial

    def _roi_path(self, lesion_id, ref):
        folder = Path("data/rois") / self.exam_id / _safe_id(lesion_id)
        path = Path(ref or "")
        if path.parent != folder or not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
            raise ValueError("ROI 引用不属于当前检查与病灶")
        return _local_path(self.root, path)

    def load_roi(self, lesion_id: str) -> tuple[np.ndarray, dict]:
        _, measurement = _records(self.bundle, _safe_id(lesion_id))
        record = _read_json(self._roi_path(lesion_id, measurement["roi_ref"]))
        try:
            if (record["exam_id"] != self.exam_id or record["lesion_id"] != lesion_id
                    or record["pet_series_ref"] != self.bundle["exam"]["pet_series_ref"]):
                raise ValueError
            _check_slice(record["slice_index"], record["sop_uid"])
            if (datetime.fromisoformat(record["at"]).tzinfo is None
                    or not isinstance(record["edited"], bool)):
                raise ValueError
            shape = tuple(record["shape"])
            if len(shape) != 2 or not all(type(n) is int and n > 0 for n in shape):
                raise ValueError
            seed = tuple(record["seed"])
            _check_seed(shape, *seed, record["fraction"])
            packed = base64.b64decode(record.pop("mask_bits"), validate=True)
            size = math.prod(shape)
            if len(packed) != (size + 7) // 8:
                raise ValueError
            bits = np.unpackbits(np.frombuffer(packed, dtype=np.uint8), count=size)
            mask = bits.astype(bool).reshape(shape)
            record["seed"] = seed
            return mask, record
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("ROI 版本文件与当前病灶或图像尺寸不符") from exc

    def save_roi(self, mask: np.ndarray, *, slice_index: int, sop_uid: str, seed: tuple[int, int],
                 fraction: float, label: str, lesion_id: str | None = None, edited: bool = False) -> str:
        mask = np.asarray(mask)
        _check_seed(mask.shape, *seed, fraction)
        if mask.dtype != np.bool_ or not mask.any():
            raise ValueError("请保留至少一个 ROI 像素后再保存")
        _check_slice(slice_index, sop_uid)
        label = label.strip()
        if not label:
            raise ValueError("请填写病灶部位标签")

        base = self.bundle
        bundle = deepcopy(base)
        at = datetime.now(timezone.utc).isoformat()
        previous_ref = None
        if lesion_id is None:
            lesion_id = "les_" + uuid4().hex
            event = {"at": at, "actor": "user" if edited else "system", "from": "draft",
                     "to": "proposed", "note": "已保存人工修订的 PET 轮廓" if edited else "已生成 PET 种子生长轮廓"}
            lesion = {"lesion_id": lesion_id, "exam_id": self.exam_id, "status": "proposed", "audit": [event]}
            measurement = {"measurement_id": "meas_" + uuid4().hex, "lesion_id": lesion_id,
                           "state": "proposed", "audit": [event.copy()]}
            bundle["lesions"].append(lesion)
            bundle["measurements"].append(measurement)
        else:
            lesion, measurement = _records(bundle, _safe_id(lesion_id))
            if lesion["status"] != "proposed" or measurement["state"] != "proposed":
                raise ValueError("只能编辑待确认的病灶轮廓")
            previous_ref = measurement["roi_ref"]
            if previous_ref:
                self.load_roi(lesion_id)  # The prior revision must remain readable.
            edited = True

        ref = f"data/rois/{self.exam_id}/{lesion_id}/{uuid4().hex}.json"
        version_path = self._roi_path(lesion_id, ref)
        lesion["label"] = label
        measurement.update(roi_ref=ref, edited=edited, suv_max=None, longest_diameter_mm=None)
        _validate_bundle(bundle)
        record = {
            "exam_id": self.exam_id, "lesion_id": lesion_id, "label": label,
            "pet_series_ref": bundle["exam"]["pet_series_ref"], "sop_uid": sop_uid,
            "slice_index": int(slice_index), "seed": list(map(int, seed)), "fraction": float(fraction),
            "algorithm": "seed_fraction_4_connected_v1", "shape": list(mask.shape),
            "mask_bits": base64.b64encode(np.packbits(mask).tobytes()).decode("ascii"),
            "previous_ref": previous_ref, "at": at, "actor": "user" if edited else "system",
            "operator": getpass.getuser(), "edited": edited,
        }
        with _writer_lock(self.lock_path):
            if _read_json(self.path) != base:
                raise ValueError("其他窗口已更新此检查，请重新打开后再编辑")
            # The exam manifest is the commit point. Readers only see complete versions.
            _write_json(version_path, record)
            try:
                _write_json(self.path, bundle)
            except OSError:
                version_path.unlink(missing_ok=True)
                raise
            self.bundle = bundle
        return lesion_id
