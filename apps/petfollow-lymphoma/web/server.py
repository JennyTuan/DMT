"""Loopback-only browser entry point for the lymphoma follow-up research prototype."""

import argparse
import base64
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys
from threading import RLock
from uuid import uuid4

import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT))

from fixtures.make_demo import make_demo_pair
from imaging import load_study
from geometry import ImageGeometry, alignment_offset
from lesion_voi import grow_lesion
from mpr import reconstruct
from fusion import pet_on_ct
from manual_params import read_manual, effective_headers, save_manual, revoke_manual
from key_image import key_object_bytes
from assessment import evidence_for, read_assessments, confirm_assessment
from reference_voi import (sample_reference_voxels, reference_outline, read_references,
                           save_reference, confirm_reference, REFERENCE_SHAPES)
from roi_store import StudyStore, grow_region
from suv import suv_for_roi, _scale
from diameter import diameter_for_roi
from ct_dimensions import dimensions_for_roi
from pairing import Pairing
from report_draft import ReportDraft, comparison_rows, _cell
from quality_gate import evaluate_bundle

CLIENT_DIST = Path(__file__).parent / "client" / "dist"


def _png(array, modality, mask=None, *, marker=None, outlines=(), spacing=None,
         center=40.0, width=400.0, pet_max=None):
    values = np.asarray(array, dtype=np.float32)
    if modality == "ct":
        gray = np.clip((values - (center - width / 2)) / width * 255, 0, 255).astype(np.uint8)
        rgb = np.repeat(gray[..., None], 3, axis=2)
    else:
        # Display-only scaling; it is never used for quantitative calculations.
        high = max(float(pet_max) if pet_max is not None else float(np.percentile(values, 99.7)), 1.0)
        ratio = np.clip(values / high, 0, 1)
        stops = np.array([[0, 0, 0], [55, 27, 22], [130, 55, 37],
                          [220, 113, 47], [255, 229, 173]], dtype=float)
        positions = ratio * (len(stops) - 1)
        left = np.minimum(positions.astype(int), len(stops) - 2)
        rgb = (stops[left] * (1 - (positions - left))[..., None]
               + stops[left + 1] * (positions - left)[..., None]).astype(np.uint8)
    if mask is not None:
        edge = mask & ~(
            np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
            & np.roll(mask, 1, 1) & np.roll(mask, -1, 1)
        )
        rgb[edge] = (83, 226, 213)
    image = Image.fromarray(rgb, "RGB")
    if spacing is not None:
        height, image_width = image.height, image.width
        physical_ratio = (height * spacing[0]) / (image_width * spacing[1])
        if physical_ratio >= 1:
            target = (max(1, round(900 / physical_ratio)), 900)
        else:
            target = (900, max(1, round(900 * physical_ratio)))
        image = image.resize(target, Image.Resampling.BILINEAR)
    if outlines:
        draw = ImageDraw.Draw(image)
        for x, y, rx, ry, color in outlines:
            draw.ellipse((x - rx, y - ry, x + rx, y + ry), outline=color, width=2)
    if marker is not None:
        x, y = marker
        draw = ImageDraw.Draw(image)
        segments = [((x - 9, y), (x - 3, y)), ((x + 3, y), (x + 9, y)),
                    ((x, y - 9), (x, y - 3)), ((x, y + 3), (x, y + 9))]
        for start, end in segments:
            draw.line((start, end), fill="#101820", width=3)
            draw.line((start, end), fill="#A9C2D0", width=1)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = RLock()
        self.studies = {}
        self.stores = {}
        self.default_id = None
        self.dimension_cache = {}

    def enrich_bundle(self, bundle):
        if bundle is None:
            return None
        result = deepcopy(bundle)
        exam_id = result["exam"]["exam_id"]
        result["exam"]["manual_input"] = read_manual(self.root, exam_id)
        if exam_id not in self.studies:
            return result
        study, store = self.get(exam_id)
        for measurement in result["measurements"]:
            key = (exam_id, measurement.get("roi_ref"))
            if key not in self.dimension_cache:
                try:
                    mask, meta = store.load_roi(measurement["lesion_id"])
                    self.dimension_cache[key] = dimensions_for_roi(study, mask, meta["slice_index"])
                except ValueError as exc:
                    self.dimension_cache[key] = (None, str(exc))
            dimensions, note = self.dimension_cache[key]
            measurement["ct_dimensions_note"] = note
            measurement["ct_long_mm"] = dimensions["long_mm"] if dimensions else None
            measurement["ct_short_mm"] = dimensions["short_mm"] if dimensions else None
            measurement["ct_spd_mm2"] = dimensions["spd_mm2"] if dimensions else None
            measurement["ct_index"] = dimensions["ct_index"] if dimensions else None
        return result

    def load(self, directory):
        study = load_study(Path(directory))

        def measure(mask, index, sop_uid):
            if not 0 <= index < len(study.pet_uids) or study.pet_uids[index] != sop_uid:
                raise ValueError("ROI 与 PET 实例不符")
            if mask.shape not in (study.pet[index].shape, study.pet.shape):
                raise ValueError("ROI 与 PET 图像尺寸不符")
            manual = read_manual(self.root, study.exam["exam_id"])
            headers = effective_headers(study.pet_headers, manual) if manual else None
            suv, suv_note = suv_for_roi(study, mask, index, headers=headers)
            diameter, diameter_note = diameter_for_roi(study, mask, index)
            return ({"suv_max": suv, "longest_diameter_mm": diameter},
                    {"suv_max": suv_note, "longest_diameter_mm": diameter_note})

        store = StudyStore(self.root, study.exam, measure=measure)
        exam_id = study.exam["exam_id"]
        self.studies[exam_id] = study
        self.stores[exam_id] = store
        self.default_id = exam_id
        return exam_id

    def demo(self):
        baseline_dir, current_dir = make_demo_pair(self.root / "data/fixtures")
        baseline_id = self.load(baseline_dir)
        current_id = self.load(current_dir)
        Pairing(self.stores[current_id]).ensure_demo_prior(baseline_id)
        return current_id

    def get(self, exam_id=None):
        key = exam_id or self.default_id
        if key not in self.studies:
            raise ValueError("检查未载入，请先载入示意病例或导入影像")
        return self.studies[key], self.stores[key]

    def state(self, exam_id=None):
        study, store = self.get(exam_id)
        pairing = Pairing(store)
        current, prior = pairing.snapshot()
        current, prior = self.enrich_bundle(current), self.enrich_bundle(prior)
        exams = [s.exam for s in self.studies.values()
                 if s.exam["patient_pseudo_id"] == study.exam["patient_pseudo_id"]]
        saved_references = read_references(self.root, study.exam["exam_id"])
        payload = {
            "exam": current["exam"], "exams": sorted(exams, key=lambda e: e["study_datetime"]),
            "lesions": current["lesions"], "measurements": current["measurements"],
            "prior": prior["exam"] if prior else None,
            "prior_lesions": prior["lesions"] if prior else [],
            "rows": comparison_rows(current, prior),
            "candidates": pairing.candidates(),
            "pet_count": len(study.pet), "ct_count": len(study.ct),
            "exam_counts": {e.exam["exam_id"]: {"pet": len(e.pet), "ct": len(e.ct)}
                            for e in self.studies.values()},
            "exam_shapes": {e.exam["exam_id"]: {"pet": list(e.pet.shape[1:]),
                                                    "ct": list(e.ct.shape[1:])}
                            for e in self.studies.values()},
            "pet_shape": list(study.pet.shape[1:]), "ct_shape": list(study.ct.shape[1:]),
            "correction_label": study.correction_label + (" · [Manual Input]" if current["exam"].get("manual_input") else ""),
            "gates": evaluate_bundle(current, prior),
            "references": {kind: versions[-1] for kind, versions in saved_references.items() if versions},
        }
        saved_assessments = read_assessments(self.root, study.exam["exam_id"])
        payload["assessments"] = {}
        for lesion in payload["lesions"]:
            lesion_id = lesion["lesion_id"]
            context = evidence_for(payload, lesion_id)
            versions = saved_assessments.get(lesion_id, [])
            latest = versions[-1] if versions else None
            payload["assessments"][lesion_id] = {
                "suggestion": context["suggestion"], "fingerprint": context["fingerprint"],
                "evidence": context["evidence"], "confirmed": latest,
                "stale": bool(latest and latest["fingerprint"] != context["fingerprint"]),
            }
        return payload


def create_app(root=ROOT, workspace=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
    work = workspace or Workspace(root)
    app.config["WORKSPACE"] = work

    @app.errorhandler(ValueError)
    def value_error(exc):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(KeyError)
    def key_error(exc):
        return jsonify({"error": f"缺少字段：{exc.args[0]}"}), 400

    @app.get("/api/state")
    def state():
        with work.lock:
            return jsonify(work.state(request.args.get("exam_id")))

    @app.post("/api/demo")
    def demo():
        with work.lock:
            return jsonify({"exam_id": work.demo()})

    @app.post("/api/import")
    def import_directory():
        raw = (request.get_json() or {}).get("path", "")
        if not raw:
            raise ValueError("请填写服务器本机 data/ 下的 PET/CT 目录")
        directory = Path(raw)
        if not directory.is_absolute():
            directory = work.root / "data" / directory
        directory = directory.resolve()
        if not directory.is_relative_to(work.root / "data"):
            raise ValueError("只允许导入仓库 data/ 下的目录")
        with work.lock:
            return jsonify({"exam_id": work.load(directory)})

    @app.post("/api/upload")
    def upload_directory():
        files = request.files.getlist("files")
        if not files or len(files) > 4000:
            raise ValueError("请选择一个 PET/CT 检查目录（最多 4000 个文件）")
        destination = (work.root / "data/uploads" / uuid4().hex).resolve()
        if not destination.is_relative_to(work.root / "data"):
            raise ValueError("导入目录无效")
        destination.mkdir(parents=True)
        seen = set()
        for file in files:
            parts = file.filename.replace("\\", "/").split("/")
            if any(part in ("", ".", "..") or ":" in part for part in parts):
                raise ValueError("影像文件路径无效")
            relative = Path(*parts)
            if relative in seen:
                raise ValueError("目录含同名文件，请重新选择")
            seen.add(relative)
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("影像文件路径无效")
            target.parent.mkdir(parents=True, exist_ok=True)
            file.save(target)
        with work.lock:
            return jsonify({"exam_id": work.load(destination)})

    @app.get("/api/image")
    def image():
        with work.lock:
            study, _ = work.get(request.args.get("exam_id"))
            modality = request.args.get("modality")
            if modality not in ("pet", "ct", "fusion"):
                raise ValueError("影像类型无效")
            volume = getattr(study, "ct" if modality == "fusion" else modality)
            plane = request.args.get("plane", "axial")
            if plane not in ("axial", "coronal", "sagittal", "mip"):
                raise ValueError("阅片平面无效")
            if modality == "fusion" and plane != "axial":
                raise ValueError("融合叠加目前只支持轴位")
            index = int(request.args.get("index", "0"))
            count = (len(volume) if plane == "axial" else
                     volume.shape[1] if plane == "coronal" else
                     volume.shape[2] if plane == "sagittal" else 1)
            if not 0 <= index < count:
                raise ValueError("切片超出范围")
            center = float(request.args.get("center", "40"))
            width = float(request.args.get("width", "400"))
            pet_max = request.args.get("pet_max")
            if not np.isfinite([center, width]).all() or width <= 0:
                raise ValueError("窗宽窗位无效")
            if pet_max is not None and (not np.isfinite(float(pet_max)) or float(pet_max) <= 0):
                raise ValueError("PET 强度范围无效")
            if modality == "fusion":
                opacity = float(request.args.get("opacity", "0.45"))
                if not np.isfinite(opacity) or not 0 <= opacity <= 1:
                    raise ValueError("融合透明度应在 0 到 1 之间")
                sampled, valid, _ = pet_on_ct(study, index)
                ct_rgb = np.asarray(Image.open(_png(volume[index], "ct", center=center, width=width)), dtype=float)
                pet_rgb = np.asarray(Image.open(_png(sampled, "pet", pet_max=float(pet_max) if pet_max else None)), dtype=float)
                alpha = opacity * valid[..., None]
                mixed = Image.fromarray(np.uint8(np.clip(ct_rgb * (1 - alpha) + pet_rgb * alpha, 0, 255)), "RGB")
                output = BytesIO()
                mixed.save(output, format="PNG")
                output.seek(0)
                return send_file(output, mimetype="image/png")
            outlines = []
            if modality == "pet" and plane == "axial":
                records = read_references(work.root, study.exam["exam_id"])
                geometry = ImageGeometry.from_headers(study.pet_headers) if records else None
                for kind, versions in records.items():
                    if kind not in REFERENCE_SHAPES or not versions:
                        continue
                    record = versions[-1]
                    if record.get("series_ref") != study.exam["pet_series_ref"]:
                        continue
                    outline = reference_outline(geometry, record["center_mm"], kind, index)
                    if outline is not None:
                        outlines.append((*outline, "#BDA3D2" if kind == "blood_pool" else "#D8B06C"))
            if plane == "axial":
                pixels, spacing = volume[index], None
            else:
                pixels, spacing = reconstruct(volume, getattr(study, modality + "_headers"), plane, index)
            return send_file(_png(pixels, modality, outlines=outlines, spacing=spacing,
                                  center=center, width=width,
                                  pet_max=float(pet_max) if pet_max else None), mimetype="image/png")

    @app.post("/api/align")
    def align():
        body = request.get_json() or {}

        def mark(name):
            value = body.get(name)
            if not isinstance(value, dict) or type(value.get("index")) is not int:
                raise ValueError("单点对齐需要两期 PET 的层号与标志点")
            point = value.get("point")
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(item) not in (int, float) for item in point)
                    or not np.isfinite(point).all()):
                raise ValueError("单点对齐标志点无效")
            return value["index"], point

        with work.lock:
            current, current_store = work.get(body.get("exam_id"))
            prior_id = Pairing(current_store).snapshot()[0]["exam"].get("prior_exam_id")
            if not prior_id:
                raise ValueError("请先关联同一患者的基线检查")
            base, _ = work.get(prior_id)
            if base.exam["patient_pseudo_id"] != current.exam["patient_pseudo_id"]:
                raise ValueError("两期患者标识不一致")
            geometries = {
                "basePet": ImageGeometry.from_headers(base.pet_headers),
                "baseCt": ImageGeometry.from_headers(base.ct_headers),
                "currentPet": ImageGeometry.from_headers(current.pet_headers),
                "currentCt": ImageGeometry.from_headers(current.ct_headers),
            }
            reference = np.asarray(geometries["basePet"].normal)
            if any(np.asarray(item.normal) @ reference < 0.999 for item in geometries.values()):
                raise ValueError("PET/CT 切片方向不一致，不能进行同步空间翻层")
            base_index, base_xy = mark("base")
            current_index, current_xy = mark("current")
            offset = alignment_offset(geometries["basePet"], geometries["currentPet"],
                                      base_index, base_xy, current_index, current_xy)
            locations = {key: [float(np.asarray(origin) @ reference) for origin in item.origins]
                         for key, item in geometries.items()}
            return jsonify({"offset_mm": offset,
                            "offset_along_normal_mm": float(np.asarray(offset) @ reference),
                            "slice_locations": locations,
                            "base_exam_id": prior_id, "current_exam_id": current.exam["exam_id"]})

    @app.post("/api/reference")
    def reference_voi():
        body = request.get_json() or {}
        kind = body.get("kind")
        if kind not in REFERENCE_SHAPES:
            raise ValueError("请选择血池或肝脏内参")
        index = body.get("index")
        point = body.get("point")
        if (type(index) is not int or not isinstance(point, list) or len(point) != 2
                or any(type(value) not in (int, float) for value in point)
                or not np.isfinite(point).all()):
            raise ValueError("内参选点无效")
        with work.lock:
            study, _ = work.get(body.get("exam_id"))
            geometry = ImageGeometry.from_headers(study.pet_headers)
            center_mm = geometry.pixel_to_patient(index, *point)
            values = sample_reference_voxels(study.pet, geometry, center_mm, kind)
            suv_max = suv_mean = None
            note = ""
            if study.exam.get("attenuation_corrected") is not True:
                note = "缺失或未确认衰减校正，不能输出正式 SUV"
            else:
                try:
                    manual = read_manual(work.root, study.exam["exam_id"])
                    scale, note = _scale(effective_headers(study.pet_headers, manual))
                    if manual:
                        note += " [Manual Input]"
                    suv_max = float(values.max() * scale)
                    suv_mean = float(values.mean() * scale)
                except ValueError as exc:
                    note = str(exc)
            record = save_reference(work.root, study.exam["exam_id"], kind, {
                "series_ref": study.exam["pet_series_ref"], "index": index,
                "seed": point, "center_mm": center_mm,
                "shape": REFERENCE_SHAPES[kind], "voxel_count": int(values.size),
                "raw_max": float(values.max()), "raw_mean": float(values.mean()),
                "raw_units": str(study.pet_headers[0].get("Units", "unknown")),
                "suv_max": suv_max, "suv_mean": suv_mean,
                "status": "needs_review" if suv_max is None else "proposed",
                "note": note, "placement_confirmed": False,
            })
            return jsonify(record)

    @app.post("/api/reference/confirm")
    def reference_confirm():
        body = request.get_json() or {}
        with work.lock:
            study, _ = work.get(body.get("exam_id"))
            record = confirm_reference(work.root, study.exam["exam_id"], body.get("kind"),
                                       body.get("version"), body.get("reviewer", ""))
            return jsonify(record)

    @app.post("/api/manual-params")
    def manual_parameters():
        body = request.get_json() or {}
        with work.lock:
            study, store = work.get(body.get("exam_id"))
            record = save_manual(work.root, study.exam["exam_id"], study.pet_headers,
                                 body.get("source_a"), body.get("source_b"), body.get("reviewer", ""))
            store.refresh_quality()
            return jsonify({"record": record, "state": work.state(study.exam["exam_id"])})

    @app.post("/api/manual-params/revoke")
    def manual_parameters_revoke():
        body = request.get_json() or {}
        with work.lock:
            study, store = work.get(body.get("exam_id"))
            event = revoke_manual(work.root, study.exam["exam_id"], body.get("reviewer", ""),
                                  body.get("reason", ""))
            store.refresh_quality()
            return jsonify({"record": event, "state": work.state(study.exam["exam_id"])})

    @app.post("/api/assessment/confirm")
    def assessment_confirm():
        body = request.get_json() or {}
        with work.lock:
            state = work.state(body.get("exam_id"))
            item = confirm_assessment(work.root, state, body.get("lesion_id"),
                                      body.get("fingerprint"), body.get("score"),
                                      body.get("category"), body.get("reviewer", ""),
                                      body.get("reason", ""))
            return jsonify(item)

    @app.post("/api/roi/preview")
    def roi_preview():
        body = request.get_json() or {}
        with work.lock:
            study, _ = work.get(body.get("exam_id"))
            index = int(body["index"])
            display_index = int(body.get("display_index", index))
            if not 0 <= index < len(study.pet) or not 0 <= display_index < len(study.pet):
                raise ValueError("PET 切片超出范围")
            seed = body["seed"]
            fraction = float(body["fraction"])
            geometry = ImageGeometry.from_headers(study.pet_headers)
            mask, detail = grow_lesion(study.pet, geometry, index, int(seed[0]), int(seed[1]), fraction)
            output = _png(study.pet[display_index], "pet", mask[display_index],
                          marker=(int(seed[0]), int(seed[1])) if display_index == index else None)
            return jsonify({"image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(),
                            "pixels": int(mask[display_index].sum()), **detail})

    @app.post("/api/roi")
    def save_roi():
        body = request.get_json() or {}
        with work.lock:
            study, store = work.get(body.get("exam_id"))
            index = int(body["index"])
            if not 0 <= index < len(study.pet):
                raise ValueError("PET 切片超出范围")
            seed = tuple(map(int, body["seed"]))
            fraction = float(body["fraction"])
            geometry = ImageGeometry.from_headers(study.pet_headers)
            mask, _ = grow_lesion(study.pet, geometry, index, *seed, fraction)
            lesion_id = store.save_roi(mask, slice_index=index, sop_uid=study.pet_uids[index],
                                       seed=seed, fraction=fraction, label=str(body["label"]),
                                       lesion_id=body.get("lesion_id"), edited=bool(body.get("lesion_id")))
            return jsonify({"lesion_id": lesion_id, "state": work.state(study.exam["exam_id"])})

    @app.get("/api/roi")
    def get_roi():
        with work.lock:
            study, store = work.get(request.args.get("exam_id"))
            mask, meta = store.load_roi(request.args["lesion_id"])
            index = meta["slice_index"]
            return jsonify({"index": index, "seed": meta["seed"], "fraction": meta["fraction"],
                            "label": meta["label"], "image": "data:image/png;base64:" +
                            base64.b64encode(_png(study.pet[index], "pet", mask[index] if mask.ndim == 3 else mask,
                                                  marker=meta["seed"]).getvalue()).decode()})

    @app.post("/api/value")
    def edit_value():
        body = request.get_json() or {}
        with work.lock:
            _, store = work.get(body.get("exam_id"))
            store.edit_value(body["lesion_id"], body["field"], body["value"], body["note"])
            return jsonify(work.state(body.get("exam_id")))

    @app.get("/api/history")
    def history():
        with work.lock:
            _, store = work.get(request.args.get("exam_id"))
            return jsonify(store.value_history(request.args["lesion_id"]))

    @app.post("/api/prior")
    def set_prior():
        body = request.get_json() or {}
        with work.lock:
            _, store = work.get(body.get("exam_id"))
            Pairing(store).set_prior(body.get("prior_exam_id"))
            return jsonify(work.state(body.get("exam_id")))

    @app.post("/api/pair")
    def pair():
        body = request.get_json() or {}
        with work.lock:
            _, store = work.get(body.get("exam_id"))
            pairing = Pairing(store)
            if body.get("prior_lesion_id"):
                pairing.pair(body["lesion_id"], body["prior_lesion_id"])
            else:
                pairing.unpair(body["lesion_id"])
            return jsonify(work.state(body.get("exam_id")))

    def draft_for(exam_id):
        _, store = work.get(exam_id)
        current, prior = Pairing(store).snapshot()
        current, prior = work.enrich_bundle(current), work.enrich_bundle(prior)
        return ReportDraft(work.root, current, prior), current, prior

    def confirmed_appendix(exam_id):
        state = work.state(exam_id)
        lines = []
        for lesion in state["lesions"]:
            item = state["assessments"].get(lesion["lesion_id"], {})
            confirmed = item.get("confirmed")
            if not confirmed or item.get("stale"):
                continue
            if not lines:
                lines = ["", "## 医生确认的辅助判读", "", "以下结果由标注医生确认；来源变更后不再导出旧确认。", ""]
            lines.extend([
                f"- {_cell(lesion['label'])}：Deauville {confirmed['score']}；Lugano {confirmed['category']}。",
                f"  确认人：{_cell(confirmed['reviewer'])}；依据：{_cell(confirmed['reason'])}；时间：{confirmed['confirmed_at']}。",
            ])
        return "\n".join(lines) + "\n" if lines else ""

    @app.get("/api/report")
    def report_get():
        with work.lock:
            draft, _, _ = draft_for(request.args.get("exam_id"))
            return jsonify({"generated": draft.generated, "description": draft.description,
                            "gates": draft.gate_results,
                            "confirmed_appendix": confirmed_appendix(draft.exam_id)})

    @app.post("/api/report")
    def report_post():
        body = request.get_json() or {}
        with work.lock:
            draft, current, prior = draft_for(body.get("exam_id"))
            draft.description = str(body.get("description", ""))
            if body.get("regenerate"):
                draft.regenerate(current, prior)
            draft.save(current, prior)
            return jsonify({"generated": draft.generated, "description": draft.description,
                            "gates": draft.gate_results,
                            "confirmed_appendix": confirmed_appendix(draft.exam_id)})

    @app.get("/api/report/export")
    def report_export():
        with work.lock:
            draft, current, prior = draft_for(request.args.get("exam_id"))
            contents = (draft.check_current(current, prior) + confirmed_appendix(draft.exam_id)).encode("utf-8")
            return send_file(BytesIO(contents), mimetype="text/markdown", as_attachment=True,
                             download_name="lymphoma-followup-draft.md")

    @app.get("/api/key-image/export")
    def key_image_export():
        with work.lock:
            study, store = work.get(request.args.get("exam_id"))
            lesion_id = request.args.get("lesion_id")
            if not lesion_id:
                raise ValueError("请选择病灶后导出 Key Image")
            contents = key_object_bytes(study, store, lesion_id)
            return send_file(BytesIO(contents), mimetype="application/dicom", as_attachment=True,
                             download_name="lymphoma-key-image-ko.dcm")

    @app.get("/")
    def index():
        if not (CLIENT_DIST / "index.html").is_file():
            return "网页尚未构建，请先运行 npm run build。", 503
        return send_from_directory(CLIENT_DIST, "index.html")

    @app.get("/<path:path>")
    def assets(path):
        return send_from_directory(CLIENT_DIST, path)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="淋巴瘤 PET 随访网页原型")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False)
