"""
Arrival-type detection.

Determines WALKING / CAR / BIKE from a single scene image using a
PRETRAINED YOLO object detector (Ultralytics YOLOv8n, COCO-trained). No
arrival-type classifier is trained here - only simple spatial-association
rules on top of YOLO's detections, per the prototype spec.

Rule (intentionally simple - swap for real multi-object tracking later
without touching callers):
  1. Detect all `person`, `car`, `motorcycle`, `bicycle` boxes.
  2. Take the highest-confidence detected person as the "subject".
  3. Find the nearest vehicle box to that person (center-distance relative
     to the person's own box size).
  4. If that vehicle is close enough -> CAR or BIKE. Otherwise -> WALKING.
  5. If no person is detected at all, report UNKNOWN rather than guessing.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from app.core.config import settings

_model_lock = threading.Lock()
_yolo_model = None

PERSON = "person"
CAR = "car"
MOTORCYCLE = "motorcycle"
BICYCLE = "bicycle"
RELEVANT_CLASSES = {PERSON, CAR, MOTORCYCLE, BICYCLE}

# How close (relative to the person box's own size) a vehicle's center must
# be to that person's center to count as "associated" with them.
ASSOCIATION_DISTANCE_RATIO = 2.5


def get_yolo_model():
    """Load the pretrained YOLO model once and cache it."""
    global _yolo_model
    if _yolo_model is None:
        with _model_lock:
            if _yolo_model is None:
                from ultralytics import YOLO
                # If YOLO_MODEL_PATH doesn't exist locally yet, ultralytics
                # will download the standard COCO-pretrained weights for
                # that filename (e.g. "yolov8n.pt") automatically.
                _yolo_model = YOLO(settings.YOLO_MODEL_PATH)
    return _yolo_model


def _box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _box_size(box):
    x1, y1, x2, y2 = box
    return max(x2 - x1, y2 - y1) or 1.0


def _distance(c1, c2):
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5


@dataclass
class ArrivalDetection:
    arrival_type: str  # WALKING / CAR / BIKE / UNKNOWN
    detected_objects: list = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self):
        return {
            "arrival_type": self.arrival_type,
            "detected_objects": self.detected_objects,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def detect_arrival_type(image_bgr: np.ndarray) -> ArrivalDetection:
    model = get_yolo_model()
    results = model.predict(image_bgr, verbose=False)[0]

    detections = []
    for box in results.boxes:
        cls_name = model.names[int(box.cls[0])]
        if cls_name not in RELEVANT_CLASSES:
            continue
        detections.append({
            "class": cls_name,
            "confidence": round(float(box.conf[0]), 4),
            "box": [round(v, 1) for v in box.xyxy[0].tolist()],
        })

    people = [d for d in detections if d["class"] == PERSON]
    vehicles = [d for d in detections if d["class"] in (CAR, MOTORCYCLE, BICYCLE)]

    if not people:
        return ArrivalDetection(
            arrival_type="UNKNOWN", detected_objects=detections, confidence=0.0,
            reason="No person detected in the frame.",
        )

    subject = max(people, key=lambda d: d["confidence"])
    subject_center = _box_center(subject["box"])
    subject_size = _box_size(subject["box"])

    best_vehicle, best_ratio = None, None
    for v in vehicles:
        ratio = _distance(subject_center, _box_center(v["box"])) / subject_size
        if best_ratio is None or ratio < best_ratio:
            best_ratio, best_vehicle = ratio, v

    if best_vehicle is not None and best_ratio <= ASSOCIATION_DISTANCE_RATIO:
        arrival_type = "CAR" if best_vehicle["class"] == CAR else "BIKE"
        confidence = round(min(subject["confidence"], best_vehicle["confidence"]), 4)
        reason = (f"Person associated with nearby {best_vehicle['class']} "
                  f"(distance_ratio={best_ratio:.2f} <= {ASSOCIATION_DISTANCE_RATIO}).")
    else:
        arrival_type = "WALKING"
        confidence = subject["confidence"]
        reason = ("No vehicle detected close enough to the person."
                  if vehicles else "No vehicle detected in the frame.")

    return ArrivalDetection(
        arrival_type=arrival_type, detected_objects=detections,
        confidence=confidence, reason=reason,
    )
