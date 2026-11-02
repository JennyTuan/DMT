"""Manual longitudinal lesion identity and the local two-exam commit."""

import getpass
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from roi_store import (StudyStore, _StudyFiles, _local_path, _read_json, _safe_id,
                       _validate_bundle, _write_json, _writer_lock)


def eligible_prior(current_exam, candidate_exam):
    return (candidate_exam["patient_pseudo_id"] == current_exam["patient_pseudo_id"]
            and candidate_exam["exam_id"] != current_exam["exam_id"]
            and datetime.fromisoformat(candidate_exam["study_datetime"])
            < datetime.fromisoformat(current_exam["study_datetime"]))


def _audit_path(root, exam_id):
    return _local_path(root, Path("data/pairings") / (_safe_id(exam_id) + ".json"))


def _read_audit(root, exam_id):
    path = _audit_path(root, exam_id)
    if not path.exists():
        return {"version": 1, "revision": None, "events": []}
    audit = _read_json(path)
    if (not isinstance(audit, dict) or audit.get("version") != 1
            or not isinstance(audit.get("revision"), str) or not isinstance(audit.get("events"), list)
            or any(not isinstance(e, dict) or e.get("current_exam_id") != exam_id
                   or e.get("actor") not in ("user", "system")
                   or e.get("action") not in ("set_prior", "pair", "unpair", "new_track", "existing_track")
                   for e in audit["events"])):
        raise ValueError("配对留痕文件无法读取，请核对数据目录")
    return audit


def _restore(root, journal, *, exams_locked=False):
    if not journal.exists():
        return
    pending = _read_json(journal)
    # Replacing the audit is the commit point for all affected manifests.
    if _read_audit(root, pending["current_exam_id"])["revision"] != pending["revision"]:
        with ExitStack() as locks:
            for exam_id, previous in pending["previous_bundles"].items():
                files = _StudyFiles(root, exam_id)
                if not exams_locked:
                    locks.enter_context(_writer_lock(files.lock_path))
                _validate_bundle(previous)
                if previous["exam"]["exam_id"] != exam_id:
                    raise ValueError("配对恢复记录的检查标识不符")
                if _read_json(files.path) != previous:
                    _write_json(files.path, previous)
    journal.unlink()


@contextmanager
def workspace_lock(root):
    """Serialize cross-exam commits with every StudyStore open and write."""
    lock = _local_path(root, Path("data/pairings/.lock"))
    lock.parent.mkdir(parents=True, exist_ok=True)
    with _writer_lock(lock):
        _restore(root, _local_path(root, Path("data/pairings/.pending")))
        yield


def _read_bundle(files):
    files._recover()  # Pack 03 may have stopped after replacing this manifest.
    bundle = _read_json(files.path)
    _validate_bundle(bundle)
    if bundle["exam"]["exam_id"] != files.exam_id:
        raise ValueError("检查文件名与检查标识不符")
    return bundle


def _track(lesion):
    value = lesion.get("lesion_track_id")
    return value if value and value.strip() else None


def _by_track(bundle):
    tracks = {}
    for lesion in bundle["lesions"]:
        track = _track(lesion)
        if track is not None:
            if track in tracks:
                raise ValueError("同一检查中多个病灶使用了同一个跟踪号，请先核对配对")
            tracks[track] = lesion
    return tracks


def _lesion(bundle, lesion_id):
    for lesion in bundle["lesions"]:
        if lesion["lesion_id"] == lesion_id:
            return lesion
    raise ValueError("所选病灶不属于此检查，请重新选择")


def _links(bundles):
    """Existing edges from a follow-up lesion to its selected prior lesion."""
    indexes = {exam_id: _by_track(bundle) for exam_id, bundle in bundles.items()}
    links = set()
    for exam_id, bundle in bundles.items():
        prior_id = bundle["exam"]["prior_exam_id"]
        for track, peer in indexes.get(prior_id, {}).items():
            current = indexes[exam_id].get(track)
            if current:
                links.add((exam_id, current["lesion_id"], prior_id, peer["lesion_id"]))
    return links


def _event(action, current, prior_id, lesion=None, peer=None, before=None, after=None, *, actor="user", **details):
    return {"action": action, "at": datetime.now(timezone.utc).isoformat(),
            "actor": actor, "operator": "demo" if actor == "system" else getpass.getuser(),
            "current_exam_id": current["exam"]["exam_id"],
            "prior_exam_id": prior_id, "current_lesion_id": lesion["lesion_id"] if lesion else None,
            "prior_lesion_id": peer["lesion_id"] if peer else None,
            "track_before": before, "track_after": after, **details}


class Pairing:
    def __init__(self, store: StudyStore):
        self.store = store
        self._seen_prior = None

    @contextmanager
    def _patient_bundles(self):
        with self.store._writing(), ExitStack() as locks:
            current = self.store.bundle["exam"]
            bundles = {self.store.exam_id: self.store.bundle}
            for path in self.store.path.parent.glob("*.json"):
                if path == self.store.path:
                    continue
                files = _StudyFiles(self.store.root, path.stem)
                # Patient identity is immutable. Only lock and recover this patient's studies.
                record = _read_json(files.path)
                if not isinstance(record, dict) or not isinstance(record.get("exam"), dict):
                    raise ValueError("检查数据无法读取，请核对本地检查文件")
                exam = record["exam"]
                if exam.get("patient_pseudo_id") == current["patient_pseudo_id"]:
                    locks.enter_context(_writer_lock(files.lock_path))
                    bundles[path.stem] = _read_bundle(files)
            yield bundles

    def candidates(self):
        with self._patient_bundles() as bundles:
            current = self.store.bundle["exam"]
            exams = [b["exam"] for b in bundles.values() if eligible_prior(current, b["exam"])]
            return sorted(exams, key=lambda e: datetime.fromisoformat(e["study_datetime"]), reverse=True)

    def snapshot(self):
        with self.store._writing():
            current = deepcopy(self.store.bundle)
            _by_track(current)
            prior_id = current["exam"]["prior_exam_id"]
            prior = None
            if prior_id is not None:
                if prior_id == self.store.exam_id:
                    raise ValueError("不能将本次检查作为先验")
                files = _StudyFiles(self.store.root, prior_id)
                with _writer_lock(files.lock_path):
                    prior = _read_bundle(files)
                if not eligible_prior(current["exam"], prior["exam"]):
                    raise ValueError("先验必须是同一患者较早的检查，请重新关联上次")
                _by_track(prior)
            self._seen_prior = deepcopy(prior)
            return current, prior

    def prior_bundle(self):
        return self.snapshot()[1]

    def has_prior_decision(self):
        with self.store._writing():
            return self._has_prior_decision()

    def _has_prior_decision(self):
        audit = _read_audit(self.store.root, self.store.exam_id)
        return any(e["action"] == "set_prior" for e in audit["events"])

    @contextmanager
    def _edit(self):
        with self._patient_bundles() as original:
            current_id = self.store.exam_id
            current = deepcopy(original[current_id])
            prior_id = current["exam"]["prior_exam_id"]
            prior = original.get(prior_id)
            if prior and not eligible_prior(current["exam"], prior["exam"]):
                prior = None
            if self._seen_prior is not None and self._seen_prior != prior:
                raise ValueError("先验检查已更新，请重新打开或刷新后再配对")
            prior = deepcopy(prior)
            events = []
            yield current, prior, original, events
            if not events:
                return
            updated = {**original, current_id: current}
            if prior:
                updated[prior_id] = prior
            for exam_id, lesion_id, _, _ in _links(original) ^ _links(updated):
                # Allow only the selected lesions in this visit to change links.
                if exam_id != current_id or not any(e["current_lesion_id"] == lesion_id
                                                     or e["action"] == "set_prior" for e in events):
                    raise ValueError("此修改会改变其他检查的既有配对，请先在相关随访检查中解除配对")
            changes = {key: bundle for key, bundle in updated.items() if original[key] != bundle}
            self._commit(changes, original, events)
            self.store.bundle = current
            self._seen_prior = deepcopy(updated.get(current["exam"]["prior_exam_id"]))

    def _commit(self, changes, original, events):
        root, current_id = self.store.root, self.store.exam_id
        for bundle in changes.values():
            _validate_bundle(bundle)
        audit = _read_audit(root, current_id)
        audit["revision"] = uuid4().hex
        audit["events"].extend(events)
        journal = _local_path(root, Path("data/pairings/.pending"))
        _write_json(journal, {"current_exam_id": current_id, "revision": audit["revision"],
                              "previous_bundles": {key: original[key] for key in changes}})
        try:
            for key, bundle in changes.items():
                _write_json(_StudyFiles(root, key).path, bundle)
            _write_json(_audit_path(root, current_id), audit)
        except OSError:
            _restore(root, journal, exams_locked=True)
            raise
        try:
            journal.unlink()
        except OSError:
            pass  # A later open finishes cleanup without replaying committed events.

    def set_prior(self, exam_id: str | None):
        self._select_prior(exam_id, demo=False)

    def ensure_demo_prior(self, baseline_id: str):
        """Seed the sample pair once, including when opening a pre-Pack 04 demo."""
        self._select_prior(_safe_id(baseline_id), demo=True)

    def _select_prior(self, exam_id, *, demo):
        with self._edit() as (current, prior, bundles, events):
            candidate = None
            if exam_id is not None:
                candidate = bundles.get(_safe_id(exam_id))
                if candidate is None or not eligible_prior(current["exam"], candidate["exam"]):
                    raise ValueError("请选择同一患者较早的既有检查")
            previous = current["exam"]["prior_exam_id"]
            if demo:
                if not (current["exam"].get("is_synthetic") and candidate["exam"].get("is_synthetic")):
                    raise ValueError("仅示意检查允许初始化示意关联")
                if previous is not None or self._has_prior_decision():
                    return
            actor = "system" if demo else "user"
            if previous != exam_id:
                old_peers = _by_track(prior) if prior else {}
                new_peers = _by_track(candidate) if candidate else {}
                for lesion in current["lesions"]:
                    track = _track(lesion)
                    if track in old_peers:
                        events.append(_event("unpair", current, previous, lesion, old_peers[track], track))
                        lesion["lesion_track_id"] = None
                    elif track in new_peers:
                        # Both manifests already record this identity. Preserve it and record its provenance.
                        events.append(_event("existing_track", current, exam_id, lesion, new_peers[track],
                                             track, track, actor=actor))
            current["exam"]["prior_exam_id"] = exam_id
            events.append(_event("set_prior", current, exam_id, previous_prior_exam_id=previous, actor=actor))

    def pair(self, current_lesion_id, prior_lesion_id):
        with self._edit() as (current, prior, _, events):
            if prior is None:
                raise ValueError("请先关联同一患者的上次检查")
            lesion, peer = _lesion(current, current_lesion_id), _lesion(prior, prior_lesion_id)
            previous = _track(lesion)
            existing = _track(peer)
            if previous is not None and previous == existing:
                return
            prior_id = prior["exam"]["exam_id"]
            old_peer = _by_track(prior).get(previous)
            if old_peer:
                events.append(_event("unpair", current, prior_id, lesion, old_peer, previous))
            track = existing or (previous if not old_peer else None) or uuid4().hex
            owner = _by_track(current).get(track)
            if owner and owner != lesion:
                raise ValueError("该先验病灶已与本次另一病灶配对，请先解除该配对")
            lesion["lesion_track_id"] = peer["lesion_track_id"] = track
            events.append(_event("pair", current, prior_id, lesion, peer, previous, track,
                                 prior_track_before=existing, prior_track_after=track))

    def unpair(self, current_lesion_id):
        self._replace_track(current_lesion_id, "unpair")

    def new_track(self, current_lesion_id):
        self._replace_track(current_lesion_id, "new_track")

    def _replace_track(self, lesion_id, action):
        with self._edit() as (current, prior, _, events):
            lesion = _lesion(current, lesion_id)
            previous = _track(lesion)
            peer = _by_track(prior).get(previous) if prior else None
            if action == "unpair" and peer is None:
                return
            track = uuid4().hex if action == "new_track" else None
            lesion["lesion_track_id"] = track
            events.append(_event(action, current, current["exam"]["prior_exam_id"], lesion, peer, previous, track))
