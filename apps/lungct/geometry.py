"""Reuse PET's unmodified geometry class; add CT gates and inverse mapping."""
from dataclasses import asdict
import importlib.util
from pathlib import Path
import sys
import numpy as np

_name = '_dmt_pet_geometry_for_lungct'
if _name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_name, Path(__file__).parents[1] / 'petfollow-lymphoma' / 'geometry.py')
    _module = importlib.util.module_from_spec(_spec); sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
ImageGeometry = sys.modules[_name].ImageGeometry


def from_dict(value):
    return ImageGeometry(**value)


def inspect(headers):
    geometry = ImageGeometry.from_headers(headers)
    problems, metrics = [], {}
    normal = np.asarray(geometry.normal)
    metrics['tilt_degrees'] = float(np.degrees(np.arccos(np.clip(abs(normal[2]), 0, 1))))
    if metrics['tilt_degrees'] > 5: problems.append('TILT')
    locations = np.asarray(geometry.locations)
    if len(locations) < 2:
        problems.append('TOO_FEW_SLICES')
    else:
        steps = np.diff(locations); median = float(np.median(steps))
        metrics.update(step_mm=median, max_step_error_mm=float(np.max(abs(steps-median))))
        if median <= 0 or metrics['max_step_error_mm'] > max(.1, median*.05):
            problems.append('IRREGULAR_SPACING')
        shifts = np.asarray(geometry.origins) - geometry.origins[0]
        # Reject gantry shear, even when the normal itself is axial.
        if np.max(abs(shifts @ geometry.row)) > .1 or np.max(abs(shifts @ geometry.column)) > .1:
            problems.append('INPLANE_SHIFT')
    return geometry, problems, metrics


def serialize(geometry):
    # JSON normalizes tuples to lists, including in first-import responses.
    import json
    return json.loads(json.dumps(asdict(geometry)))


def patient_to_pixel(geometry, point, *, require_plane=False):
    point = np.asarray(point, dtype=float)
    if point.shape != (3,) or not np.isfinite(point).all(): raise ValueError('坐标必须是有限 LPS 毫米三元组')
    index = geometry.nearest_index(point)
    delta = point - geometry.origins[index]
    x = float(delta @ geometry.row / geometry.spacing[1])
    y = float(delta @ geometry.column / geometry.spacing[0])
    if not (-1e-6 <= x <= geometry.columns-1+1e-6 and -1e-6 <= y <= geometry.rows-1+1e-6):
        raise ValueError('坐标超出原片范围')
    distances = np.asarray(geometry.locations)
    location = float(point @ geometry.normal)
    if location < distances[0]-.001 or location > distances[-1]+.001: raise ValueError('坐标超出序列范围')
    if require_plane and abs(delta @ geometry.normal) > .01: raise ValueError('径线端点必须在同一原始层面')
    return index, x, y


def direction(vector):
    letters = [('左 L', '右 R'), ('后 P', '前 A'), ('头 S', '足 I')]
    return ' / '.join(letters[i][0 if vector[i]>0 else 1] for i in np.argsort(-np.abs(vector)) if abs(vector[i])>.2)
