"""
Face enrollment.

For every person already created by scripts/seed_demo_database.py (matched
by `name` == dataset folder name), reads every image in
FACE_DATASET_TRAIN_DIR/<name>/*.jpeg, extracts an ArcFace embedding, and
stores it in the face_embeddings table.

A person can have multiple embeddings (one per training image) - the
recognition nearest-neighbour search in face_service.py naturally handles
multiple embeddings per identity.

Run (from project root):
    python ml/face_recognition/enrollment.py
    python ml/face_recognition/enrollment.py --person ABHAY   # only one person
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Person, FaceEmbedding  # noqa: E402
from app.services.face_service import extract_embedding  # noqa: E402

IMAGE_EXTENSIONS = ("*.jpeg", "*.jpg", "*.png")


def list_images(person_dir: str) -> list[str]:
    files = []
    for pattern in IMAGE_EXTENSIONS:
        files.extend(glob.glob(os.path.join(person_dir, pattern)))
    return sorted(files)


def main(only_person: str | None = None):
    train_dir = settings.face_train_path
    if not os.path.isdir(train_dir):
        print(f"[ERROR] Train dir not found: {train_dir}")
        sys.exit(1)

    people_dirs = sorted(
        d for d in os.listdir(train_dir)
        if os.path.isdir(os.path.join(train_dir, d)) and not d.startswith(".")
    )
    if only_person:
        people_dirs = [p for p in people_dirs if p == only_person]

    db = SessionLocal()
    total_images = 0
    total_embeddings = 0
    no_face_count = 0

    try:
        for name in people_dirs:
            person = db.query(Person).filter_by(name=name).first()
            if not person:
                print(f"[SKIP] No Person row for '{name}' - run seed_demo_database.py first")
                continue

            person_dir = os.path.join(train_dir, name)
            images = list_images(person_dir)
            print(f"\n{name} (person_id={person.id}): {len(images)} training images")

            for img_path in images:
                total_images += 1
                image_bgr = cv2.imread(img_path)
                if image_bgr is None:
                    print(f"  [WARN] Could not read image: {img_path}")
                    continue

                result = extract_embedding(image_bgr)
                if result.embedding is None:
                    no_face_count += 1
                    print(f"  [WARN] No face detected: {os.path.basename(img_path)}")
                    continue

                # Avoid duplicate enrollment on re-runs
                exists = db.query(FaceEmbedding).filter_by(person_id=person.id, image_path=img_path).first()
                if exists:
                    print(f"  [SKIP] Already enrolled: {os.path.basename(img_path)}")
                    continue

                db.add(FaceEmbedding(
                    person_id=person.id,
                    embedding=result.embedding.tolist(),
                    image_path=img_path,
                ))
                total_embeddings += 1
                print(f"  [OK] Enrolled: {os.path.basename(img_path)} (det_score={result.det_score:.3f})")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("\n--- Enrollment summary ---")
    print(f"Images processed: {total_images}")
    print(f"Embeddings stored: {total_embeddings}")
    print(f"No-face-detected images: {no_face_count}")
    if no_face_count:
        print("NOTE: images with no detected face were skipped. Check lighting/crop "
              "quality if this count is high relative to total images.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--person", default=None, help="Only enroll this one folder/person name")
    args = parser.parse_args()
    main(only_person=args.person)
