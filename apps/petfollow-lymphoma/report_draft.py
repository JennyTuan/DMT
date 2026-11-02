"""Lesion comparisons and version 1 local descriptive report drafts."""

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

from pairing import eligible_prior
from roi_store import _local_path, _safe_id, _write_json, _writer_lock


BANNER = "原型·不可用于临床诊疗决策"


def _require_descriptive(text):
    # Apply the pack's explicit output exclusions to free text as well as imported labels.
    if re.search(r"Deauville|Lugano|(?<![a-z])(?:CMR|PMR|NMR|PMD)(?![a-z])|缓解|恶性|辅助诊断|疗效结论",
                 text, re.IGNORECASE):
        raise ValueError("本草稿仅保存描述性内容。请核对病灶部位和手写描述后再试。")


def _linked_prior(current, prior):
    exam = current["exam"]
    if (prior is not None and exam.get("prior_exam_id") == prior["exam"]["exam_id"]
            and eligible_prior(exam, prior["exam"])):
        return prior
    return None


def _findings(bundle):
    measurements = defaultdict(list)
    for record in bundle["measurements"]:
        measurements[record["lesion_id"]].append(record)
    findings = []
    for lesion in bundle["lesions"]:
        records = measurements[lesion["lesion_id"]]
        # The workstation edits one measurement per lesion. Never pick an arbitrary one.
        measurement = records[0] if len(records) == 1 else {}
        findings.append((lesion, measurement))
    return findings


def _difference(current, prior):
    return current - prior if current is not None and prior is not None else None


def _row(current, prior):
    lesion, measure = current or ({}, {})
    previous, before = prior or ({}, {})
    suv, prior_suv = measure.get("suv_max"), before.get("suv_max")
    mm, prior_mm = measure.get("longest_diameter_mm"), before.get("longest_diameter_mm")
    return {
        "lesion_id": lesion.get("lesion_id"), "prior_lesion_id": previous.get("lesion_id"),
        "label": (lesion or previous)["label"], "prior_label": previous.get("label"),
        "track_id": (lesion or previous).get("lesion_track_id"),
        "current_suv": suv, "prior_suv": prior_suv, "delta_suv": _difference(suv, prior_suv),
        "current_mm": mm, "prior_mm": prior_mm, "delta_mm": _difference(mm, prior_mm),
        "status": measure.get("state", lesion.get("status")),
        "prior_status": before.get("state", previous.get("status")),
    }


def comparison_rows(current_bundle, prior_bundle=None):
    """One row per current lesion, followed by unmatched lesions from a valid linked prior."""
    current = _findings(current_bundle)
    linked = _linked_prior(current_bundle, prior_bundle)
    earlier = _findings(linked) if linked is not None else []
    current_counts = Counter(lesion.get("lesion_track_id") for lesion, _ in current)
    prior_tracks = defaultdict(list)
    for finding in earlier:
        prior_tracks[finding[0].get("lesion_track_id")].append(finding)

    rows = []
    matched_ids = set()
    for finding in current:
        track = finding[0].get("lesion_track_id")
        prior = None
        if track and track.strip() and current_counts[track] == 1 and len(prior_tracks[track]) == 1:
            prior, = prior_tracks[track]
            matched_ids.add(prior[0]["lesion_id"])
        rows.append(_row(finding, prior))
    rows.extend(_row(None, finding) for finding in earlier if finding[0]["lesion_id"] not in matched_ids)
    return rows


def _cell(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, (float, int)):
        return format(value, ".5g")
    # A site label is free text. Keep it in its cell, including when rendered as Markdown.
    safe = escape(" ".join(value.splitlines())).replace("\\", "\\\\")
    for character in ("|", "[", "]", "*", "`", "~"):
        safe = safe.replace(character, "\\" + character)
    return safe


def _table_row(*cells):
    return "| " + " | ".join(cells) + " |"


def generated_section(current, prior):
    """A markdown snapshot; each side uses the same comparisons shown by the workstation."""
    exam = current["exam"]
    prior = _linked_prior(current, prior)
    lines = [
        BANNER, "", "# 淋巴瘤 PET 随访原型 · 描述性报告草稿", "",
        f"患者代号　{_cell(exam['patient_pseudo_id'])}", "",
        "| 检查 | 检查 ID | 检查时间 | 示意数据 |", "| --- | --- | --- | --- |",
    ]
    for name, source in (("本次", exam), ("先验", prior["exam"] if prior else None)):
        if source is not None:
            lines.append(_table_row(name, _cell(source["exam_id"]), _cell(source["study_datetime"]),
                                    "是" if source.get("is_synthetic", False) else "否"))
        elif exam.get("prior_exam_id"):
            lines.append(_table_row("先验（未载入）", _cell(exam["prior_exam_id"]), "—", "—"))
        else:
            lines.append(_table_row("先验（未关联）", "—", "—", "—"))
    lines.extend([
        "", "## 病灶对照", "", "量测按「本次 / 先验 / 差值」排列。差值为本次减先验，— 表示无对应条目或数值。",
        "", "| 部位 | Track ID | SUVmax | 最长径（mm） | 状态（本次 / 先验） |",
        "| --- | --- | --- | --- | --- |",
    ])
    rows = comparison_rows(current, prior)
    for row in rows:
        _require_descriptive(row["label"])
        if row["prior_label"]:
            _require_descriptive(row["prior_label"])
        label = _cell(row["label"])
        if row["lesion_id"] is None:
            label += "（仅先验条目）"
        elif row["prior_lesion_id"] is None:
            label += "（本次未配对）"
        elif row["label"] != row["prior_label"]:
            label += " / " + _cell(row["prior_label"])
        suv = " / ".join(_cell(row[k]) for k in ("current_suv", "prior_suv", "delta_suv"))
        diameter = " / ".join(_cell(row[k]) for k in ("current_mm", "prior_mm", "delta_mm"))
        status = _cell(row["status"]) + " / " + _cell(row["prior_status"])
        lines.append(_table_row(label, _cell(row["track_id"]), suv, diameter, status))
    if not rows:
        lines.extend(["", "尚无病灶条目。"])
    return "\n".join(lines)


class ReportDraft:
    """The generated snapshot and the author's plain text have separate lifetimes."""

    def __init__(self, root, current, prior):
        self.exam_id = _safe_id(current["exam"]["exam_id"])
        self.root = Path(root).resolve()
        self.path = _local_path(self.root, Path("data/reports") / (self.exam_id + ".json"))
        self._saved = self._read_saved()
        self.generated = self._saved["generated"] if self._saved else generated_section(current, prior)
        self.description = self._saved["description"] if self._saved else ""
        self._clean = self._payload()

    def _payload(self):
        return {"version": 1, "exam_id": self.exam_id,
                "generated": self.generated, "description": self.description}

    def _read_saved(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError as exc:
            raise ValueError("草稿文件无法读取，请核对已保存的文件") from exc
        if (not isinstance(saved, dict) or saved.get("version") != 1 or saved.get("exam_id") != self.exam_id
                or not isinstance(saved.get("generated"), str) or not saved["generated"].startswith(BANNER + "\n")
                or not isinstance(saved.get("description"), str)):
            raise ValueError("草稿格式、版本或检查 ID 不符，请核对已保存的文件")
        return saved

    @property
    def dirty(self):
        return self._payload() != self._clean

    def _current_section(self, current, prior):
        if current["exam"]["exam_id"] != self.exam_id:
            raise ValueError("当前检查已切换，请重新打开对应的草稿")
        return generated_section(current, prior)

    def regenerate(self, current, prior):
        self.generated = self._current_section(current, prior)

    def check_current(self, current, prior):
        _require_descriptive(self.description)
        if self.generated != self._current_section(current, prior):
            raise ValueError("检查、配对或量测已更新，请先从当前量测重新生成")

    def save(self, current, prior):
        self.check_current(current, prior)
        path = _local_path(self.root, self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _writer_lock(_local_path(self.root, path.with_suffix(".lock"))):
            if self._read_saved() != self._saved:
                raise ValueError("另一窗口已修改草稿，可先导出当前文字，再重新打开草稿")
            payload = self._payload()
            _write_json(path, payload)
        self._saved = self._clean = payload

    def export(self, path, current, prior):
        self.check_current(current, prior)
        path = Path(path)
        if path.suffix.lower() != ".md":
            raise ValueError("请选择扩展名为 .md 的新文件")
        try:
            stream = path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise ValueError("该文件已经存在，请为此次导出选择新文件名") from exc
        try:
            with stream:
                stream.write(self.generated + "\n\n## 描述\n\n" + self.description + "\n")
        except OSError:
            path.unlink(missing_ok=True)
            raise
