"""
Standalone CLI: run the full detect -> crop -> OCR pipeline on one vehicle
image and print the recognized plate text.

Run:
    python ml/anpr/ocr.py path/to/vehicle_image.jpg
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.services.anpr_service import recognize_plate  # noqa: E402


def main(image_path: str):
    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        print(f"[ERROR] Could not read image: {image_path}")
        sys.exit(1)

    result = recognize_plate(image_bgr)
    print(f"Detector used:   {result.detector_used}")
    print(f"Plate detected:  {result.detected}")
    print(f"Raw OCR text:    {result.raw_ocr_text}")
    print(f"Normalized:      {result.plate_number}")
    print(f"OCR confidence:  {result.confidence}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    args = parser.parse_args()
    main(args.image_path)
