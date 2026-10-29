"""
Downloads a ready-to-use, ALREADY-TRAINED YOLOv8 license-plate detector
from Hugging Face and places it at PLATE_DETECTOR_MODEL_PATH (default
models/plate_detector.pt). No annotated images, training, or fine-tuning
required - this is exactly the "start with a pretrained detector" approach
the project spec calls for.

Model used: Koushim/yolov8-license-plate-detection (YOLOv8n, single class
"license_plate", MIT licensed, https://huggingface.co/Koushim/yolov8-license-plate-detection).
If you'd rather use a different pretrained plate-detector checkpoint, just
download its .pt file yourself and place it at the same path - anpr_service.py
doesn't care where the weights came from.

Run:
    pip install huggingface_hub
    python scripts/download_plate_model.py
"""
import os
import shutil
import sys

import _bootstrap  # noqa: F401  (loads .env, sets sys.path)

from app.core.config import settings

REPO_ID = "Koushim/yolov8-license-plate-detection"
FILENAME = "best.pt"


def main():
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[ERROR] huggingface_hub is not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    print(f"Downloading {FILENAME} from {REPO_ID} ...")
    downloaded_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)

    dest_path = settings.PLATE_DETECTOR_MODEL_PATH
    if not os.path.isabs(dest_path):
        from app.core.config import PROJECT_ROOT
        dest_path = os.path.join(PROJECT_ROOT, dest_path)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy(downloaded_path, dest_path)

    print(f"\nSaved plate-detector weights to: {dest_path}")
    print("anpr_service.py will now use this YOLO model instead of the Haar-cascade fallback.")
    print("Verify with:  python ml/anpr/detect_plate.py <path_to_a_vehicle_image>")


if __name__ == "__main__":
    main()
