"""Single-slice PET contours, measurements and their local revision history."""

import base64
import getpass
import hashlib
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

from quality_gate import measurement_gates

_FIELDS = ("suv_max", "longest_diameter_mm")
_EDITABLE = {"proposed", "needs_review"}
_NO_ATTENUATION = "缺/未衰减校正，SUV 仅供复核"


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
            or len({m["measurement_id"] for m in bundle["measurements"]}) != len(bundle["measurements"])
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


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("量测值必须是非负有限数值")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("量测值超出可保存范围") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError("量测值必须是非负有限数值")
    return value


def _record_value(history, measurement, field, value, actor, at, note, **source):
    if actor == "user":
        source["operator"] = getpass.getuser()
    history.setdefault(measurement["measurement_id"], []).append({
        "at": at, "actor": actor, "field": field, "from": measurement[field], "to": value,
        "note": note, "roi_ref": measurement["roi_ref"], **source,
    })
    measurement[field] = value


def _roi_source(mask, meta):
    # Shape and packed bits identify the actual contour, even if an altered
    # version file still decodes successfully on the original SOP instance.
    digest = hashlib.sha256(f"{mask.shape[0]}x{mask.shape[1]}:".encode("ascii"))
    digest.update(np.packbits(mask).tobytes())
    return {"slice_index": meta["slice_index"], "sop_uid": meta["sop_uid"],
            "mask_sha256": digest.hexdigest()}


def _current_events(history, measurement):
    return [event for event in history.get(measurement["measurement_id"], ())
            if event["roi_ref"] == measurement["roi_ref"]]


def _source_errors(events):
    latest = {e["field"]: e for e in events if e["actor"] == "system"}
    return {field: event["source_error"] for field, event in latest.items() if event.get("source_error")}


def _validate_events(events):
    previous = {}
    for event in events:
        field = event["field"]
        if (field not in _FIELDS or event["actor"] not in ("system", "user")
                or not isinstance(event["note"], str) or not event["note"].strip()
                or datetime.fromisoformat(event["at"]).tzinfo is None
                or not isinstance(event["roi_ref"], (str, type(None)))):
            raise ValueError
        for key in ("from", "to"):
            if event[key] is not None:
                _number(event[key])
        if field in previous and event["from"] != previous[field]:
            raise ValueError
        previous[field] = event["to"]


class _StudyFiles:
    def __init__(self, root, exam_id):
        self.root = Path(root).resolve()
        self.exam_id = _safe_id(exam_id)
        self.path = _local_path(self.root, Path("data/exams") / (self.exam_id + ".json"))
        self.lock_path = _local_path(self.root, self.path.with_suffix(".lock"))
        self.history_path = _local_path(self.root, Path("data/measurements") / (self.exam_id + ".history.json"))
        self.journal_path = _local_path(self.root, self.path.with_suffix(".pending"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_history(self):
        if not self.history_path.exists():
            return {"revision": None, "by_measurement": {}}
        data = _read_json(self.history_path)
        if (not isinstance(data, dict) or not isinstance(data.get("revision"), str)
                or not isinstance(data.get("by_measurement"), dict)
                or any(not isinstance(items, list) for items in data["by_measurement"].values())):
            raise ValueError("数值留痕文件无法读取，请核对数据目录")
        try:
            for events in data["by_measurement"].values():
                _validate_events(events)
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("数值留痕记录不完整或前后不一致，请核对历史文件") from exc
        return data

    def _recover(self):
        if not self.journal_path.exists():
            return
        # The sidecar revision is the commit point. All store readers open under
        # the same lock, so a crashed writer's partial manifest is never loaded.
        pending = _read_json(self.journal_path)
        if self._read_history()["revision"] != pending["revision"]:
            previous = pending["previous_bundle"]
            _validate_bundle(previous)
            if previous["exam"]["exam_id"] != self.exam_id:
                raise ValueError("待恢复记录与本次检查不匹配")
            if _read_json(self.path) != previous:
                _write_json(self.path, previous)
            if pending["roi_ref"] is not None:
                self._roi_path(pending["lesion_id"], pending["roi_ref"]).unlink(missing_ok=True)
        self.journal_path.unlink()

    def _roi_path(self, lesion_id, ref):
        folder = Path("data/rois") / self.exam_id / _safe_id(lesion_id)
        path = Path(ref or "")
        if path.parent != folder or not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
            raise ValueError("ROI 引用不属于当前检查与病灶")
        return _local_path(self.root, path)

    @contextmanager
    def _locked(self):
        # Recover Pack 04 before reading/replaying this exam's Pack 03 journal.
        from pairing import workspace_lock
        with workspace_lock(self.root), _writer_lock(self.lock_path):
            yield


class StudyStore(_StudyFiles):
    def __init__(self, root: Path, exam: dict, measure=None):
        initial = {"exam": deepcopy(exam), "lesions": [], "measurements": []}
        _validate_bundle(initial)
        super().__init__(root, exam["exam_id"])
        self.measure = measure
        with self._locked():
            self._recover()
            self._history = self._read_history()
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
            if self.measure is not None:
                self._backfill()

    @contextmanager
    def _writing(self):
        with self._locked():
            self._recover()
            if _read_json(self.path) != self.bundle or self._read_history() != self._history:
                raise ValueError("其他窗口已更新此检查，请重新打开后再编辑")
            yield

    def _commit(self, bundle, history, *, roi_ref=None, record=None):
        """Commit while holding the exam writer lock; keep ROI versions immutable."""
        _validate_bundle(bundle)
        changed_history = history != self._history["by_measurement"]
        if changed_history:
            sidecar = {"revision": uuid4().hex, "by_measurement": history}
            _write_json(self.journal_path, {
                "revision": sidecar["revision"], "previous_bundle": self.bundle, "roi_ref": roi_ref,
                "lesion_id": record["lesion_id"] if record else None,
            })
        version_path = self._roi_path(record["lesion_id"], roi_ref) if record else None
        try:
            if version_path is not None:
                _write_json(version_path, record)
            if bundle != self.bundle:
                _write_json(self.path, bundle)
            if changed_history:
                _write_json(self.history_path, sidecar)
        except OSError:
            if changed_history:
                self._recover()
            elif version_path is not None:
                version_path.unlink(missing_ok=True)
            raise
        self.bundle = bundle
        if changed_history:
            self._history = sidecar
            # Once committed, cleanup can safely be retried on the next open/write.
            try:
                self.journal_path.unlink()
            except OSError:
                pass

    def value_history(self, lesion_id):
        _, measurement = _records(self.bundle, lesion_id)
        return deepcopy(self._history["by_measurement"].get(measurement["measurement_id"], []))

    def _review(self, measurement, at, *, roi_valid, field_errors, quantitative=True):
        gates = measurement_gates(self.bundle["exam"], measurement, roi_valid=roi_valid,
                                  field_errors=field_errors, quantitative=quantitative)
        reasons = [f"{g['gate_id']} · {g['message']}" for g in gates if g["level"] == "review"]
        if reasons and measurement["state"] == "proposed":
            measurement["audit"].append({"at": at, "actor": "system", "from": "proposed",
                                         "to": "needs_review", "note": "；".join(reasons)})
            measurement["state"] = "needs_review"

    def edit_value(self, lesion_id, field, value, note):
        if field not in _FIELDS or not isinstance(note, str) or not note.strip():
            raise ValueError("请选择有效的量测字段并填写修改说明")
        value = _number(value)
        with self._writing():
            bundle = deepcopy(self.bundle)
            history = deepcopy(self._history["by_measurement"])
            lesion, measurement = _records(bundle, lesion_id)
            if lesion["status"] not in _EDITABLE or measurement["state"] not in _EDITABLE:
                raise ValueError("此病灶当前状态不允许修改量测")
            at = datetime.now(timezone.utc).isoformat()
            _record_value(history, measurement, field, value, "user", at, note.strip())
            measurement["edited"] = True
            self._check_stored(measurement, history, recheck_at=at)
            self._commit(bundle, history)

    def _calculate_roi(self, mask, meta, roi_error):
        source = {}
        try:
            if roi_error:
                raise ValueError(roi_error)
            source = _roi_source(mask, meta)
            values, notes = self.measure(mask, source["slice_index"], source["sop_uid"])
            values = {f: None if values[f] is None else _number(values[f]) for f in _FIELDS}
            if not all(isinstance(notes[f], str) and notes[f].strip() for f in _FIELDS):
                raise ValueError("缺少量测依据")
        except Exception as exc:
            # A failed calculation is itself an auditable result. The source ROI
            # is still retained, including when the modality data cannot be mapped.
            reason = f"ROI 量测失败（{exc}）" if isinstance(exc, ValueError) else "ROI 量测失败，请核对影像与元数据"
            values = dict.fromkeys(_FIELDS)
            notes = dict.fromkeys(_FIELDS, reason)
        if not self.bundle["exam"]["attenuation_corrected"]:
            values["suv_max"] = None
            if _NO_ATTENUATION not in notes["suv_max"]:
                notes = {**notes, "suv_max": f"{notes['suv_max']}。{_NO_ATTENUATION}"}
        return source, values, notes

    def _measure_roi(self, measurement, history, mask, meta, at, *, current=None, roi_error=None):
        # Explicit ROI saves always generate two entries. On reopen, compare the
        # current DICOM evidence per field, keeping any prior human override.
        source, values, notes = self._calculate_roi(mask, meta, roi_error)
        latest = {e["field"]: e for e in current or ()}
        automatic = {e["field"]: e for e in current or () if e["actor"] == "system"}
        for field in _FIELDS:
            value, note = values[field], notes[field]
            evidence = source.copy()
            issue = note if value is None else None
            if issue:
                evidence["source_error"] = issue
            if current is not None:
                last = latest.get(field, {})
                prior_auto = automatic.get(field, {})
                prior_issue = prior_auto.get("source_error")
                preserved = last.get("preserved")
                if last.get("actor") == "user":
                    preserved = "manual"
                elif not last and measurement[field] is not None:
                    preserved = "legacy"  # Non-null legacy values have no provable author.
                if preserved:
                    if issue == prior_issue:
                        continue
                    value = measurement[field]
                    note += "；保留人工修订值" if preserved == "manual" else "；保留既有数值"
                    evidence["preserved"] = preserved
                elif last and value == measurement[field] and issue == prior_issue:
                    continue
            _record_value(history, measurement, field, value, "system", at, note, **evidence)
        errors = {field: notes[field] for field in _FIELDS if values[field] is None}
        self._review(measurement, at, roi_valid=roi_error is None, field_errors=errors)

    def _check_stored(self, measurement, history, *, recheck_at=None):
        """Inspect the active version. A timestamp also requests a transactional measurement recheck."""
        current = _current_events(history, measurement)
        mask = meta = roi_error = None
        try:
            mask, meta = self._read_roi(measurement)
            source = _roi_source(mask, meta)
            if any(event[k] != v for event in current for k, v in source.items() if k in event):
                raise ValueError("ROI 像素、PET 实例或层面与量测留痕不符")
        except (ValueError, OSError) as exc:
            roi_error = str(exc)

        if measurement["state"] in ("accepted", "rejected") and self.measure is not None:
            # Verify the evidence for a historical decision without changing that decision or its values.
            _, values, notes = self._calculate_roi(mask, meta, roi_error)
            return roi_error is None, {f: notes[f] for f in _FIELDS if values[f] is None}
        if recheck_at is not None:
            calculated = any(e["actor"] == "system" for e in current)
            if self.measure is not None or (calculated and roi_error is not None):
                self._measure_roi(measurement, history, mask, meta, recheck_at, current=current, roi_error=roi_error)
                current = _current_events(history, measurement)
            else:
                # Contour-only Pack 02 records have no numeric calculation to assess.
                self._review(measurement, recheck_at, roi_valid=roi_error is None,
                             field_errors=_source_errors(current), quantitative=calculated)
        return roi_error is None, _source_errors(current)

    def quality_evidence(self):
        """Read mask validity and current automatic source errors by measurement ID."""
        validity, errors = {}, {}
        for m in self.bundle["measurements"]:
            key = m["measurement_id"]
            validity[key], errors[key] = self._check_stored(m, self._history["by_measurement"])
        return validity, errors

    def refresh_quality(self):
        """Recheck editable records under the writer lock and return evidence for every target."""
        with self._writing():
            return self._backfill()

    def _backfill(self):
        bundle = deepcopy(self.bundle)
        history = deepcopy(self._history["by_measurement"])
        at = datetime.now(timezone.utc).isoformat()
        validity, errors = {}, {}
        lesions = {lesion["lesion_id"]: lesion for lesion in bundle["lesions"]}
        for measurement in bundle["measurements"]:
            lesion = lesions[measurement["lesion_id"]]
            editable = measurement["state"] in _EDITABLE and lesion["status"] in _EDITABLE
            key = measurement["measurement_id"]
            validity[key], errors[key] = self._check_stored(measurement, history,
                                                            recheck_at=at if editable else None)
        if bundle != self.bundle or history != self._history["by_measurement"]:
            self._commit(bundle, history)
        return validity, errors

    def load_roi(self, lesion_id: str) -> tuple[np.ndarray, dict]:
        _, measurement = _records(self.bundle, _safe_id(lesion_id))
        return self._read_roi(measurement)

    def _read_roi(self, measurement):
        lesion_id = measurement["lesion_id"]
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
            if not mask.any():
                raise ValueError
            record["seed"] = seed
            return mask, record
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("ROI 版本文件与当前病灶或图像尺寸不符") from exc

    def save_roi(self, mask: np.ndarray, *, slice_index: int, sop_uid: str, seed: tuple[int, int],
                 fraction: float, label: str, lesion_id: str | None = None, edited: bool = False) -> str:
        with self._writing():
            return self._save_roi(mask, slice_index, sop_uid, seed, fraction, label, lesion_id, edited)

    def _save_roi(self, mask, slice_index, sop_uid, seed, fraction, label, lesion_id, edited):
        mask = np.asarray(mask)
        _check_seed(mask.shape, *seed, fraction)
        if mask.dtype != np.bool_ or not mask.any():
            raise ValueError("ROI_EMPTY · 请保留至少一个 ROI 像素后再保存")
        _check_slice(slice_index, sop_uid)
        label = label.strip()
        if not label:
            raise ValueError("请填写病灶部位标签")

        bundle = deepcopy(self.bundle)
        history = deepcopy(self._history["by_measurement"])
        at = datetime.now(timezone.utc).isoformat()
        previous_ref = None
        if lesion_id is None:
            lesion_id = "les_" + uuid4().hex
            event = {"at": at, "actor": "user" if edited else "system", "from": "draft",
                     "to": "proposed", "note": "已保存人工修订的 PET 轮廓" if edited else "已生成 PET 种子生长轮廓"}
            lesion = {"lesion_id": lesion_id, "exam_id": self.exam_id, "status": "proposed", "audit": [event]}
            measurement = {"measurement_id": "meas_" + uuid4().hex, "lesion_id": lesion_id,
                           "suv_max": None, "longest_diameter_mm": None,
                           "state": "proposed", "audit": [event.copy()]}
            bundle["lesions"].append(lesion)
            bundle["measurements"].append(measurement)
        else:
            lesion, measurement = _records(bundle, _safe_id(lesion_id))
            allowed = _EDITABLE if self.measure is not None else {"proposed"}
            if lesion["status"] not in allowed or measurement["state"] not in allowed:
                raise ValueError("只能编辑待确认的病灶轮廓")
            if self.measure is None and measurement["measurement_id"] in history:
                raise ValueError("请在可重算量测的阅片窗口编辑此轮廓")
            previous_ref = measurement["roi_ref"]
            if previous_ref:
                self.load_roi(lesion_id)  # The prior revision must remain readable.
            edited = True

        ref = f"data/rois/{self.exam_id}/{lesion_id}/{uuid4().hex}.json"
        lesion["label"] = label
        measurement.update(roi_ref=ref, edited=edited)
        record = {
            "exam_id": self.exam_id, "lesion_id": lesion_id, "label": label,
            "pet_series_ref": bundle["exam"]["pet_series_ref"], "sop_uid": sop_uid,
            "slice_index": int(slice_index), "seed": list(map(int, seed)), "fraction": float(fraction),
            "algorithm": "seed_fraction_4_connected_v1", "shape": list(mask.shape),
            "mask_bits": base64.b64encode(np.packbits(mask).tobytes()).decode("ascii"),
            "previous_ref": previous_ref, "at": at, "actor": "user" if edited else "system",
            "operator": getpass.getuser(), "edited": edited,
        }
        if self.measure is None:
            measurement.update(suv_max=None, longest_diameter_mm=None)
            self._review(measurement, at, roi_valid=True, field_errors={}, quantitative=False)
        else:
            self._measure_roi(measurement, history, mask, record, at)
        self._commit(bundle, history, roi_ref=ref, record=record)
        return lesion_id
