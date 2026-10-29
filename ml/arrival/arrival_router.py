"""
Standalone CLI for testing arrival-type detection on a single image, without
going through the API. The real implementation lives in
backend/app/services/arrival_service.py (loaded once, reused by the API) -
this file just exercises it and prints the result.

Run:
    python ml/arrival/arrival_router.py path/to/scene_image.jpg
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.services.arrival_service import detect_arrival_type  # noqa: E402


def main(image_path: str):
    if not os.path.isfile(image_path):
        print(f"[ERROR] Image not found: {image_path}")
        sys.exit(1)

    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        print(f"[ERROR] Could not read image: {image_path}")
        sys.exit(1)

    result = detect_arrival_type(image_bgr)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    args = parser.parse_args()
    main(args.image_path)
