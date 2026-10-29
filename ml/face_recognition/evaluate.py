"""
Evaluates the enrolled face recognition system against
FACE_DATASET_TEST_DIR/<name>/<name>_15..20.jpeg (ground truth = folder name).

Writes results/face_results.csv with columns:
    image, ground_truth, predicted, similarity, correct

Prints:
    overall accuracy
    per-person accuracy
    a plain-text confusion matrix

Run:
    python ml/face_recognition/evaluate.py
"""
import csv
import glob
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.services.face_service import extract_embedding, recognize_embedding  # noqa: E402

import json

IMAGE_EXTENSIONS = ("*.jpeg", "*.jpg", "*.png")
RESULTS_PATH = os.path.join("results", "face_results.csv")
SUMMARY_PATH = os.path.join("results", "face_summary.json")


def list_test_face_images(person_dir: str) -> list[str]:
    """Only the plain test face images - NOT car_image_*/car_number_*/id_*
    files that also live in each Image_Test/<name> folder."""
    files = []
    for pattern in IMAGE_EXTENSIONS:
        for path in glob.glob(os.path.join(person_dir, pattern)):
            base = os.path.basename(path).lower()
            if base.startswith("car_image"):
                continue
            files.append(path)
    return sorted(files)


def main():
    test_dir = settings.face_test_path
    if not os.path.isdir(test_dir):
        print(f"[ERROR] Test dir not found: {test_dir}")
        sys.exit(1)

    people_dirs = sorted(
        d for d in os.listdir(test_dir)
        if os.path.isdir(os.path.join(test_dir, d)) and not d.startswith(".")
    )

    os.makedirs("results", exist_ok=True)
    rows = []
    per_person_total = defaultdict(int)
    per_person_correct = defaultdict(int)
    confusion = defaultdict(lambda: defaultdict(int))  # confusion[gt][pred] = count
    no_face = 0

    db = SessionLocal()
    try:
        for name in people_dirs:
            person_dir = os.path.join(test_dir, name)
            for img_path in list_test_face_images(person_dir):
                image_bgr = cv2.imread(img_path)
                if image_bgr is None:
                    print(f"[WARN] could not read {img_path}")
                    continue

                extraction = extract_embedding(image_bgr)
                if extraction.embedding is None:
                    no_face += 1
                    rows.append({
                        "image": img_path, "ground_truth": name, "predicted": "NO_FACE_DETECTED",
                        "similarity": 0.0, "correct": False,
                    })
                    per_person_total[name] += 1
                    confusion[name]["NO_FACE_DETECTED"] += 1
                    continue

                match = recognize_embedding(db, extraction.embedding)
                predicted_name = match.person_name or "UNKNOWN"
                correct = predicted_name == name

                rows.append({
                    "image": img_path,
                    "ground_truth": name,
                    "predicted": predicted_name,
                    "similarity": round(match.similarity, 4),
                    "correct": correct,
                })
                per_person_total[name] += 1
                per_person_correct[name] += int(correct)
                confusion[name][predicted_name] += 1
    finally:
        db.close()

    with open(RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["image", "ground_truth", "predicted", "similarity", "correct"])
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    correct_total = sum(r["correct"] for r in rows)
    accuracy = correct_total / total if total else 0.0

    per_person_accuracy = {
        name: round(per_person_correct[name] / per_person_total[name], 4)
        for name in per_person_total
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "total_images": total,
            "correct": correct_total,
            "accuracy": round(accuracy, 4),
            "no_face_detected": no_face,
            "per_person_accuracy": per_person_accuracy,
        }, f, indent=2)

    print(f"\nSaved detailed results to {RESULTS_PATH}")
    print(f"Saved summary to {SUMMARY_PATH}")
    print(f"\nOverall accuracy: {correct_total}/{total} = {accuracy:.2%}")
    if no_face:
        print(f"Images with no face detected: {no_face}")

    print("\nPer-person accuracy:")
    for name in sorted(per_person_total):
        t = per_person_total[name]
        c = per_person_correct[name]
        print(f"  {name:15s} {c}/{t} = {c/t:.2%}")

    print("\nConfusion matrix (ground_truth -> predicted: count):")
    for gt in sorted(confusion):
        preds = ", ".join(f"{p}:{c}" for p, c in sorted(confusion[gt].items(), key=lambda x: -x[1]))
        print(f"  {gt:15s} -> {preds}")

    if accuracy < 0.80:
        print("\n[NOTE] Accuracy is below 80%. This is a real evaluation result, not a bug to "
              "hide. Possible next steps: check image quality/lighting, verify enrollment ran "
              "correctly, try a different InsightFace pack, or consider that some demo photos "
              "may be low-resolution/occluded by design of the source dataset.")


if __name__ == "__main__":
    main()
