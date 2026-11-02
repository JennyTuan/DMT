"""Create a reproducible, wholly synthetic thorax PET/CT DICOM study."""
import argparse
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, PositronEmissionTomographyImageStorage


def _uid(name, version):
    return f"2.25.{uuid5(NAMESPACE_URL, f'petfollow-lymphoma/{version}/{name}').int}"


def _phantom(modality, size, z, rng):
    """Analytic cross-section, in normalized field-of-view coordinates."""
    axis = (np.arange(size) + 0.5) * 2 / size - 1
    x, y = np.meshgrid(axis, axis)

    def ellipse(cx, cy, rx, ry, tilt=0):
        return ((x - cx - tilt * (y - cy)) / rx) ** 2 + ((y - cy) / ry) ** 2

    body = ellipse(0, 0.04, 0.90 - 0.025 * z, 0.67)
    left = ellipse(-0.39, 0.03, 0.33, 0.46 - 0.025 * z, 0.15)
    right = ellipse(0.40, 0.03, 0.31, 0.44 - 0.035 * z, -0.20)
    heart = ellipse(0.09 + 0.02 * z, 0.045, 0.24 + 0.05 * z, 0.29 + 0.035 * z, 0.30)
    lung = (np.minimum(left, right) < 1) & (heart > 1)
    vertebra = ellipse(0, 0.435, 0.14, 0.095)
    focus = ellipse(0.088, -0.057, 0.056, 0.050) + (z / 0.45) ** 2

    if modality == "PT":
        # A deterministic synthetic spatial pattern shared by both demo versions.
        sigmoid = lambda distance: 1 / (1 + np.exp(np.clip(15 * (distance - 1), -40, 40)))
        tissue = sigmoid(body)
        lungs = sigmoid(np.minimum(left, right)) * (1 - sigmoid(heart))
        values = tissue * (235 - 135 * lungs + 36 * np.cos(10 * x + 4 * y + z))
        values += 235 * np.exp(-2.5 * (np.sqrt(heart) - 0.82) ** 2 - 0.85 * heart)
        values += 180 * np.exp(-1.1 * vertebra) + 1900 * np.exp(-1.25 * focus)
        values += rng.normal(0, 8, values.shape) * tissue
        return np.rint(np.maximum(values, 0)).astype("<i2")

    # Chest wall and fat, lung fields, mediastinum, airway, ribs and spine.
    values = np.full(x.shape, -1000.0)
    values[body < 1] = -96
    values[body < 0.84] = 42
    values[body < 0.68] = -76
    values[lung] = -820
    values[heart < 1] = 47
    values[ellipse(-0.035, -0.11 + 0.025 * z, 0.059, 0.063) < 1] = -910
    values[ellipse(0.145, 0.22, 0.058, 0.069) < 1] = 106
    values[ellipse(-0.11, -0.20, 0.074, 0.068) < 1] = 124
    values[ellipse(-0.055, -0.57, 0.119, 0.030) < 1] = 495
    values[focus < 0.9] = 68
    for sign in (-1, 1):
        # Small paired, branching pulmonary vessels radiate from each hilum.
        for ex, ey in [(0.52, -0.32), (0.67, -0.17), (0.64, 0.19), (0.46, 0.39)]:
            dx, dy = sign * (ex - 0.22), ey - 0.035
            rx, ry = x - sign * 0.22, y - 0.035 - 0.03 * z
            t = np.clip((rx * dx + ry * dy) / (dx * dx + dy * dy), 0, 1)
            vessel = (rx - t * dx) ** 2 + (ry - t * dy) ** 2 < (0.017 - 0.012 * t) ** 2
            values[vessel & lung] = 35
        for cx, cy in [(0.44, -0.44), (0.71, -0.26), (0.78, 0.02),
                       (0.73, 0.30), (0.50, 0.50)]:
            rib = ellipse(sign * cx, cy + 0.025 * z, 0.054, 0.021, sign * cy)
            values[rib < 1] = 590
            values[rib < 0.46] = 178
    values[vertebra < 1] = 610
    values[vertebra < 0.76] = 224
    arch = ellipse(0, 0.526, 0.112, 0.069)
    values[(arch < 1) & (arch > 0.42)] = 422
    values[ellipse(0, 0.598, 0.020, 0.062) < 1] = 408
    values += rng.normal(0, 11, values.shape) * (body < 1)
    return np.rint(values).astype("<i2")


def _instance(modality, index, count, size, spacing, quantitative):
    name = f"{modality}/{index + 1:03d}"
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, preamble=b"\0" * 128, file_meta=meta)
    ds.SOPClassUID = PositronEmissionTomographyImageStorage if modality == "PT" else CTImageStorage
    version = "demo-v2" if quantitative else "demo-v1"
    ds.SOPInstanceUID = _uid(name, version)
    ds.SeriesInstanceUID = _uid(modality, version)
    ds.StudyInstanceUID = _uid("study", version)
    ds.FrameOfReferenceUID = _uid("frame", version)
    ds.Modality = modality
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.add_new(0x0008001C, "CS", "YES")  # Synthetic Data
    ds.PatientName = "SYNTHETIC^PHANTOM"
    ds.PatientID = "PETFOLLOW-SYNTHETIC-01"
    ds.StudyDescription = "Synthetic thorax phantom"
    ds.StudyDate, ds.StudyTime, ds.TimezoneOffsetFromUTC = "20260110", "090000", "+0800"
    ds.SeriesNumber = 1 if modality == "PT" else 2
    ds.InstanceNumber = index + 1
    ds.Rows, ds.Columns = size, size
    ds.PixelSpacing = [spacing, spacing]
    ds.SliceThickness = 60 / (count - 1)
    z = 2 * index / (count - 1) - 1
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [-192 + spacing / 2, -192 + spacing / 2, round(30 * z, 4)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
    ds.RescaleSlope, ds.RescaleIntercept = 1, 0
    if modality == "PT":
        ds.CorrectedImage = ["ATTN"]
        ds.Units = "CNTS"
        if quantitative:
            # v2 models a synthetic activity concentration, 8 Bq/ml per step.
            ds.Units, ds.RescaleSlope = "BQML", 8
            ds.CorrectedImage = ["ATTN", "DECY"]
            ds.DecayCorrection = "START"
            ds.SeriesType = ["STATIC", "IMAGE"]
            ds.SeriesDate = ds.AcquisitionDate = ds.StudyDate
            ds.SeriesTime = ds.AcquisitionTime = "091500"
            ds.PatientWeight = 70
            tracer = Dataset()
            tracer.Radiopharmaceutical = "Synthetic FDG"
            tracer.RadiopharmaceuticalStartDateTime = "20260110081500+0800"
            tracer.RadionuclideTotalDose = 200_000_000
            tracer.RadionuclideHalfLife = 6586.2
            ds.RadiopharmaceuticalInformationSequence = [tracer]
    rng = np.random.default_rng(401 + index + 100 * int(ds.SeriesNumber))
    ds.PixelData = _phantom(modality, size, z, rng).tobytes()
    out = BytesIO()
    ds.save_as(out, enforce_file_format=True)
    return out.getvalue()


def make_demo(directory: Path, *, quantitative=False):
    """Publish an entire series pair together. Never replace unrelated files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / ("petfollow-demo-v2" if quantitative else "petfollow-demo-v1")
    with TemporaryDirectory(dir=directory) as scratch:
        staged = Path(scratch) / output.name
        for modality, count, size, spacing in [("PT", 21, 192, 2), ("CT", 31, 256, 1.5)]:
            (staged / modality).mkdir(parents=True)
            for index in range(count):
                filename = staged / modality / f"{index + 1:03d}.dcm"
                filename.write_bytes(_instance(modality, index, count, size, spacing, quantitative))
        if not output.exists():
            try:
                staged.rename(output)
                return
            except FileExistsError:
                pass  # A concurrent run may have just published the same study.
        for instance in staged.rglob("*.dcm"):
            previous = output / instance.relative_to(staged)
            if not previous.is_file() or previous.read_bytes() != instance.read_bytes():
                raise ValueError("目标目录已含不同内容，请选择新的示意数据目录。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--quantitative", action="store_true", help="生成含合成定量参数的 v2 示意检查")
    args = parser.parse_args()
    make_demo(args.output_dir, quantitative=args.quantitative)
    print(f"示意数据 · PET 21 层 / CT 31 层 · {args.output_dir.resolve()}")
