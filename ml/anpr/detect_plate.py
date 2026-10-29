"""
Standalone CLI: run just the plate DETECTION step on an image and report
the boxes found + which detector was used (yolo vs haar_fallback).

Run:
    python ml/anpr/detect_plate.py path/to/vehicle_image.jpg
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.services.anpr_service import detect_plate_regions  # noqa: E402


def main(image_path: str):
    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        print(f"[ERROR] Could not read image: {image_path}")
        sys.exit(1)

    boxes, detector_used = detect_plate_regions(image_bgr)
    print(f"Detector used: {detector_used}")
    print(f"Boxes found: {len(boxes)}")
    for b in boxes:
        print(f"  x={b[0]} y={b[1]} w={b[2]} h={b[3]}")

    if detector_used == "haar_fallback":
        print("\n[NOTE] No YOLO plate-detector weights found at "
              "PLATE_DETECTOR_MODEL_PATH - using the weaker Haar cascade "
              "fallback. See README for how to plug in a pretrained plate "
              "detector model.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    args = parser.parse_args()
    main(args.image_path)
