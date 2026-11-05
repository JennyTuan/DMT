"""Run the optional research model without importing its libraries into the app."""
import json
import os
from pathlib import Path
import platform
import socket
import sys


def offline(*args, **kwargs):
    raise OSError('Network access is disabled for local CT inference')


def main(bundle, volume_path, output):
    settings = bundle / 'settings'
    (settings / 'Ultralytics').mkdir(parents=True, exist_ok=True)
    os.environ.update(YOLO_CONFIG_DIR=str(settings), YOLO_AUTOINSTALL='false')
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    # Keep the qualified base PyTorch runtime and isolate the optional packages.
    sys.path.extend([str(bundle / 'worker-site'), str(bundle)])
    import numpy as np
    import torch

    cuda = torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 2 * 1024 ** 3
    if not cuda:
        torch.set_num_threads(4)
    os.environ.update(LUNA_IMG_SIZE='512', LUNA_INFER_BATCH='8', LUNA_DEVICE='0' if cuda else 'cpu',
                      LUNA_INFER_HALF='1' if cuda else '0')
    from ultralytics import YOLO, __version__ as ultralytics_version
    from luna_rev.io_luna import normalize_hu
    from luna_rev.predict import cluster_to_3d, detect_volume

    volume = np.load(volume_path, allow_pickle=False, mmap_mode='r')
    detector = YOLO(str(bundle / 'model.pt'), task='detect')
    clusters = cluster_to_3d(detect_volume(detector, normalize_hu(volume), 'naive'))[:150]
    runtime = dict(python=platform.python_version(), torch=str(torch.__version__),
                   ultralytics=ultralytics_version, numpy=np.__version__, cuda=torch.version.cuda,
                   precision='float16' if cuda else 'float32',
                   device=torch.cuda.get_device_name(0) if cuda else 'CPU')
    output.write_text(json.dumps(dict(centers=clusters[:, [0, 1, 2, 5]].tolist(), runtime=runtime),
                                 allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main(*(Path(arg) for arg in sys.argv[1:]))
