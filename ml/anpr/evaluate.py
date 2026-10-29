"""
Evaluates the ANPR pipeline (detect_plate_regions + OCR) against
PLATE_DATASET_TEST_DIR/images + PLATE_DATASET_TEST_DIR/labels.csv
(columns: Image, GroundTruthNumber).

Writes results/anpr_results.csv (per-image predictions) and
results/anpr_summary.json (aggregate metrics, read by the System Status
page). Prints:
    total images
    detection success rate       (plate region found at all)
    exact match accuracy         (normalized prediction == normalized GT)
    character-level accuracy     (position-aligned char match / max len)
    character error rate (CER)   (Levenshtein distance / GT length)
    a handful of example wrong predictions

Run:
    python ml/anpr/evaluate.py
    python ml/anpr/evaluate.py --limit 50     # quick smoke test on a subset
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import _bootstrap  # noqa: F401,E402

import cv2  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.anpr_service import recognize_plate, normalize_plate_text  # noqa: E402

RESULTS_CSV = os.path.join("results", "anpr_results.csv")
RESULTS_JSON = os.path.join("results", "anpr_summary.json")


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def char_accuracy(pred: str, gt: str) -> float:
    if not gt:
        return 0.0
    n = max(len(pred), len(gt))
    matches = sum(1 for i in range(min(len(pred), len(gt))) if pred[i] == gt[i])
    return matches / n


def main(limit: int | None = None):
    test_dir = settings.plate_test_path
    images_dir = os.path.join(test_dir, "images")
    labels_path = os.path.join(test_dir, "labels.csv")

    if not os.path.isfile(labels_path):
        print(f"[ERROR] labels.csv not found at {labels_path}")
        sys.exit(1)

    with open(labels_path, "r", encoding="utf-8") as f:
        rows_in = list(csv.DictReader(f))
    if limit:
        rows_in = rows_in[:limit]

    os.makedirs("results", exist_ok=True)
    out_rows = []
    detected_count = 0
    exact_match_count = 0
    char_acc_sum = 0.0
    cer_sum = 0.0
    detector_used_counts = {}
    wrong_examples = []

    for i, row in enumerate(rows_in, start=1):
        image_name = row["Image"]
        gt_raw = row["GroundTruthNumber"]
        gt_norm = normalize_plate_text(gt_raw)
        image_path = os.path.join(images_dir, image_name)

        image_bgr = cv2.imread(image_path)
        if image_bgr is None:
            print(f"[WARN] could not read {image_path}")
            continue

        result = recognize_plate(image_bgr)
        detector_used_counts[result.detector_used] = detector_used_counts.get(result.detector_used, 0) + 1

        pred_norm = result.plate_number or ""
        is_exact = pred_norm == gt_norm and gt_norm != ""
        c_acc = char_accuracy(pred_norm, gt_norm)
        cer = levenshtein(pred_norm, gt_norm) / len(gt_norm) if gt_norm else 1.0

        if result.detected:
            detected_count += 1
        if is_exact:
            exact_match_count += 1
        char_acc_sum += c_acc
        cer_sum += cer

        out_rows.append({
            "image": image_name,
            "ground_truth": gt_norm,
            "predicted": pred_norm,
            "detected": result.detected,
            "detector_used": result.detector_used,
            "ocr_confidence": result.confidence,
            "exact_match": is_exact,
            "char_accuracy": round(c_acc, 4),
            "cer": round(cer, 4),
        })

        if not is_exact and len(wrong_examples) < 15:
            wrong_examples.append((image_name, gt_norm, pred_norm))

        if i % 50 == 0:
            print(f"  ...processed {i}/{len(rows_in)}")

    total = len(out_rows)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        writer.writeheader()
        writer.writerows(out_rows)

    detection_rate = detected_count / total if total else 0.0
    exact_accuracy = exact_match_count / total if total else 0.0
    avg_char_accuracy = char_acc_sum / total if total else 0.0
    avg_cer = cer_sum / total if total else 0.0

    summary = {
        "total_images": total,
        "detection_success_rate": round(detection_rate, 4),
        "exact_match_accuracy": round(exact_accuracy, 4),
        "character_level_accuracy": round(avg_char_accuracy, 4),
        "character_error_rate": round(avg_cer, 4),
        "detector_used_counts": detector_used_counts,
    }
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSaved per-image results to {RESULTS_CSV}")
    print(f"Saved summary to {RESULTS_JSON}")
    print(f"\nTotal images:              {total}")
    print(f"Detection success rate:    {detection_rate:.2%}")
    print(f"Exact match accuracy:      {exact_accuracy:.2%}")
    print(f"Character-level accuracy:  {avg_char_accuracy:.2%}")
    print(f"Character error rate:      {avg_cer:.2%}")
    print(f"Detector usage:            {detector_used_counts}")

    if detector_used_counts.get("haar_fallback", 0) > 0:
        print("\n[NOTE] Some/all images used the Haar-cascade fallback detector "
              "(no YOLO plate weights configured). This is typically the main "
              "cause of low accuracy - see README for sourcing a pretrained "
              "license-plate YOLO model before considering fine-tuning.")

    if wrong_examples:
        print("\nExample wrong predictions (image, ground_truth, predicted):")
        for ex in wrong_examples:
            print(f"  {ex}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N rows (quick test)")
    args = parser.parse_args()
    main(limit=args.limit)
