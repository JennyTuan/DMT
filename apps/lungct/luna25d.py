"""Opt-in adapter for the published LUNA16 2.5D research detector."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np

from . import VERSION
from .core import digest
from .model import DETECTION_TASK


VERSION_TAG = 'Exp3-fold0@d9bc7ec'
WEIGHT_SHA256 = '8d85810389124d89bc0fa2a8bdd2ba2bcf8349e9c907c1b9591b89ed264c7d36'
# Pinned files from the same upstream revision as the checkpoint.
SOURCE_HASHES = {
    '__init__.py': 'f4b6fe8a72e9fa8b3ba6986d245f1b79709da46b967511396cd3aea29de22aad',
    'config.py': '15abe8d9dd0212e8d0a2ac3b4092fe47a987531c843ffd4dd39d54e1624b1dc0',
    'io_luna.py': '25dab9ca831648967618b754afea4117d993e2d8e707939978fc00dacc5be894',
    'predict.py': 'cad76fe26c4e4bfb2578ed238a72ba1a20cc3bacc249c840ca159e96f8a99118',
    'splits.py': '3ec096ffbe4e8347af70f73a820d1fecf8fb69ddbe8b631b61c38331860f2577',
}
PREPROCESSING = dict(orientation='native axial', hu_range=[-1000, 400], image_size=512,
                     representation='adjacent-slice 2.5D', slice_confidence_floor=.01,
                     nms=.45, slice_max_detections=30, cluster_z_margin=3,
                     cluster_iou=.1, candidate_cap=150)


class Luna25DAdapter:
    selection = dict(id='luna16-yolo11n-exp3-fold0', label='LUNA16 2.5D',
                     name='Lien-Feng/Lightweight-2-5D-LUNA16', version='Exp3 · Fold 0',
                     task=DETECTION_TASK)

    def __init__(self, bundle):
        self.bundle = Path(bundle).resolve(strict=True)
        self.worker = Path(__file__).with_name('luna25d_worker.py')
        self.metadata()

    def metadata(self):
        weights = self.bundle / 'model.pt'
        if not weights.is_file():
            raise ValueError('WEIGHTS_MISSING')
        if not (self.bundle / 'worker-site' / 'ultralytics' / '__init__.py').is_file():
            raise ValueError('MODEL_DEPENDENCIES')
        expected = {weights: WEIGHT_SHA256}
        expected.update({self.bundle / 'luna_rev' / name: sha for name, sha in SOURCE_HASHES.items()})
        for path, sha in expected.items():
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('MODEL_VERSION')
        implementation = [hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (Path(__file__), self.worker)]
        return dict(name=self.selection['name'], version=VERSION_TAG, weight_sha256=WEIGHT_SHA256,
                    license='CC-BY-4.0', execution_profile='isolated-research', software_version=VERSION,
                    adapter_sha256=digest([*implementation, SOURCE_HASHES]),
                    preprocessing=dict(PREPROCESSING), preprocessing_sha256=digest(PREPROCESSING))

    def predict(self, volume, geometry, threshold):
        with TemporaryDirectory(prefix='lungct-luna25d-') as directory:
            output = Path(directory) / 'results.json'
            process = subprocess.run([sys.executable, '-I', str(self.worker), str(self.bundle),
                                      str(volume.filename), str(output)], capture_output=True,
                                     encoding='utf-8', errors='replace', timeout=300,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if process.returncode:
                if 'out of memory' in process.stderr.lower():
                    raise MemoryError('Detector ran out of memory')
                if 'ImportError' in process.stderr or 'ModuleNotFoundError' in process.stderr:
                    raise ValueError('MODEL_DEPENDENCIES')
                raise RuntimeError('Local detector worker failed')
            result = json.loads(output.read_text(encoding='utf-8'))

        x_axis = np.asarray(geometry.row) * geometry.spacing[1]
        y_axis = np.asarray(geometry.column) * geometry.spacing[0]
        transform = np.eye(4)
        transform[:3, :3] = np.column_stack((x_axis, y_axis,
            np.asarray(geometry.normal) * np.median(np.diff(geometry.locations))))
        transform[:3, 3] = geometry.origins[0]
        candidates = []
        for z, x, y, score in result['centers']:
            if not np.isfinite([z, x, y, score]).all() or not (
                z == int(z) and 0 <= z < len(volume) and 0 <= x <= 1 and 0 <= y <= 1 and 0 <= score <= 1
            ):
                raise ValueError('INVALID_RESULTS')
            if score < threshold:
                continue
            point = np.asarray(geometry.origins[int(z)])
            point = point + x_axis * min(x * geometry.columns, geometry.columns - 1)
            point = point + y_axis * min(y * geometry.rows, geometry.rows - 1)
            candidates.append(dict(center_lps=point.tolist(), box_lps=None, score=score))
        return dict(candidates=candidates, model_to_lps=transform.tolist(), runtime=result['runtime'])
