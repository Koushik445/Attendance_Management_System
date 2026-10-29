"""
Recognize a single face image against the enrolled database.
Useful for quick manual testing before wiring up the API.

Run:
    python ml/face_recognition/recognize.py path/to/image.jpg
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.services.face_service import extract_embedding, recognize_embedding  # noqa: E402


def main(image_path: str):
    if not os.path.isfile(image_path):
        print(f"[ERROR] Image not found: {image_path}")
        sys.exit(1)

    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        print(f"[ERROR] Could not read image: {image_path}")
        sys.exit(1)

    extraction = extract_embedding(image_bgr)
    if extraction.embedding is None:
        print("No face detected in image.")
        return

    db = SessionLocal()
    try:
        match = recognize_embedding(db, extraction.embedding)
    finally:
        db.close()

    print(f"Faces detected: {extraction.num_faces_detected} (det_score={extraction.det_score:.3f})")
    print(f"Predicted person_id: {match.person_id}")
    print(f"Predicted name:      {match.person_name}")
    print(f"Similarity:          {match.similarity:.4f}")
    print(f"Confidence:          {match.confidence_label}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    args = parser.parse_args()
    main(args.image_path)
