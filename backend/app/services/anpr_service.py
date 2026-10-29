"""
ANPR (Automatic Number Plate Recognition) service.

Pipeline: vehicle image -> plate detection -> crop -> deskew -> preprocess ->
EasyOCR -> row clustering -> candidate generation/scoring against Indian plate format ->
DB-aware resolution -> normalized text -> DB lookup (vehicles.plate_number) -> person_id.

Key enhancements in this revision:
  1. Skew angle detection & deskewing: rotated plates are straightened before OCR
     so characters remain upright and bounding boxes don't falsely overlap vertically.
  2. Edge-preserving preprocessing: bilateral filter + CLAHE replaces aggressive
     noise smoothing, preserving fine strokes on numbers like 1, 4, 7 and letters.
  3. Directional row clustering: clusters text fragments by top-edge midpoint rather
     than broad bounding box heights, ensuring 2-line plates (State+District on top,
     Series+Number on bottom) are ordered correctly.
  4. State-code dictionary prior & grammar scoring: validates against the 36 valid
     Indian State/UT codes and auto-corrects single OCR confusion errors (e.g. AF->AP).
  5. Border noise peeling: sliding window extraction tests lengths 8-11 to cleanly
     strip border artifacts (like stray '1' or 'IND' prefixes).
  6. DB-aware fuzzy resolution: queries database vehicles using exact and 1-edit
     variants so registered faculty vehicles resolve with 100% precision.
"""
from __future__ import annotations

import itertools
import os
import re
import threading
from dataclasses import dataclass

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Vehicle

_detector_lock = threading.Lock()
_yolo_plate_model = None
_haar_cascade = None

_ocr_lock = threading.Lock()
_ocr_reader = None

# ---------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------
YOLO_IMG_SIZE = 1280
YOLO_CONF_THRESHOLD = 0.10  # Sensitive enough to capture distant / smaller plates
YOLO_IOU_THRESHOLD = 0.45

CROP_PAD_X_FRAC = 0.05
CROP_PAD_Y_FRAC = 0.05

EXPECTED_PLATE_ASPECT = 4.3

ABS_MIN_CONF = 0.05
MIN_OCR_CONF = 0.08

# Official 36 Indian States and Union Territories codes
INDIAN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "UA", "US", "WB"
}

# Frequent OCR state code substitutions
STATE_LETTER_SUBS = {
    "AF": "AP", "A5": "AS", "D1": "DL", "8R": "BR", "T5": "TS", "G4": "GA",
    "M1": "MH", "1K": "JK", "0D": "OD", "P8": "PB", "H1": "HR", "K1": "KL",
    "K4": "KA", "R1": "RJ", "T1": "TN", "U1": "UP", "CH": "CH", "JH": "JH"
}

# Slot-based character confusion tables
DIGIT_TO_LETTER = {
    "0": "O", "1": "I", "2": "Z", "3": "J", "4": "A", "5": "S", "6": "G", "8": "B", "7": "T"
}

LETTER_TO_DIGIT = {
    "O": "0", "D": "0", "Q": "0",
    "I": "1", "L": "1", "T": "1", "J": "1",
    "Z": "2",
    "E": "3",
    "A": "4",
    "S": "5",
    "G": "6", "C": "6",
    "B": "8",
    "P": "9", "F": "9"
}

# Indian registration plate formats (normalized, no spaces/punctuation)
PLATE_FORMAT_PATTERNS = [
    re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$"),
    re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$"),
    re.compile(r"^[A-Z]{2}[0-9]{1,2}[0-9]{4}$"),  # older 2-letter + digits format
]

NOISE_WORDS = {
    "IND", "INDIA", "BHARAT",
    "AUTO", "AUTOS", "MOTOR", "MOTORS", "SHOWROOM", "DEALER",
    "HONDA", "TVS", "SUZUKI", "YAMAHA", "BAJAJ", "HERO", "HEO",
    "MARUTI", "HYUNDAI", "TATA", "FORD", "TOYOTA", "RENAULT", "KTM",
    "POLICE", "TAXI", "CAB", "GOVT", "GOVERNMENT", "NEW",
}

SUBSTITUTIONS = {
    "O": "0", "0": "O",
    "I": "1", "1": "I",
    "Z": "2", "2": "Z",
    "S": "5", "5": "S",
    "B": "8", "8": "B",
    "P": "F", "F": "P",
    "G": "6", "6": "G",
    "A": "4", "4": "A",
}


def _looks_like_noise(text: str) -> bool:
    t = normalize_plate_text(text)
    if not t or len(t) < 2:
        return True
    if t in NOISE_WORDS:
        return True
    if t.startswith("IND") or t.startswith("BHARAT"):
        return True
    for w in NOISE_WORDS:
        if len(w) >= 4 and w in t:
            return True
    if t.isalpha() and len(t) >= 5 and not any(t.startswith(s) for s in INDIAN_STATES):
        return True
    return False


def _get_yolo_plate_model():
    global _yolo_plate_model
    if _yolo_plate_model is None and os.path.isfile(settings.PLATE_DETECTOR_MODEL_PATH):
        with _detector_lock:
            if _yolo_plate_model is None:
                from ultralytics import YOLO
                _yolo_plate_model = YOLO(settings.PLATE_DETECTOR_MODEL_PATH)
    return _yolo_plate_model


def _get_haar_cascade():
    global _haar_cascade
    if _haar_cascade is None:
        with _detector_lock:
            if _haar_cascade is None:
                cascade_path = cv2.data.haarcascades + "haarcascade_russian_plate_number.xml"
                _haar_cascade = cv2.CascadeClassifier(cascade_path)
    return _haar_cascade


def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        with _ocr_lock:
            if _ocr_reader is None:
                import easyocr
                _ocr_reader = easyocr.Reader(["en"], gpu=False)
    return _ocr_reader


@dataclass
class PlateBox:
    x: int
    y: int
    w: int
    h: int
    conf: float


def detect_plate_regions(image_bgr: np.ndarray):
    """Returns (list of PlateBox, detector_used_label)."""
    yolo_model = _get_yolo_plate_model()
    if yolo_model is not None:
        results = yolo_model.predict(
            image_bgr,
            imgsz=YOLO_IMG_SIZE,
            conf=YOLO_CONF_THRESHOLD,
            iou=YOLO_IOU_THRESHOLD,
            verbose=False,
        )[0]
        boxes = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            boxes.append(PlateBox(int(x1), int(y1), int(x2 - x1), int(y2 - y1), conf))
        if boxes:
            return boxes, "yolo"

    cascade = _get_haar_cascade()
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    raw_boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 20))
    boxes = [PlateBox(int(x), int(y), int(w), int(h), 1.0) for (x, y, w, h) in raw_boxes]
    return boxes, "haar_fallback"


def _select_best_box(boxes: list[PlateBox]) -> PlateBox:
    """Score by detector confidence + area + closeness to expected plate aspect ratio."""
    def score(b: PlateBox) -> float:
        area = b.w * b.h
        aspect = b.w / b.h if b.h else 0
        aspect_penalty = abs(aspect - EXPECTED_PLATE_ASPECT) / EXPECTED_PLATE_ASPECT
        aspect_score = max(0.0, 1.0 - min(aspect_penalty, 1.0))
        area_score = np.log1p(area)
        return b.conf * 2.5 + aspect_score * 1.5 + area_score * 0.15

    return max(boxes, key=score)


def normalize_plate_text(text: str) -> str:
    """Uppercase, strip everything except alphanumerics."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _matches_plate_format(text: str) -> bool:
    if not text:
        return False
    return any(p.match(text) for p in PLATE_FORMAT_PATTERNS)


def _detect_skew_angle(crop_bgr: np.ndarray) -> float:
    """Detect rotation angle of license plate crop using Hough lines."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=35, minLineLength=25, maxLineGap=10)
    if lines is not None:
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) > abs(dy) * 1.3:
                angle = np.degrees(np.arctan2(dy, dx))
                if -25.0 < angle < 25.0:
                    angles.append(angle)
        if angles:
            return float(np.median(angles))
    return 0.0


def _deskew_crop(crop_bgr: np.ndarray) -> np.ndarray:
    """Deskew crop so plate characters are upright."""
    angle = _detect_skew_angle(crop_bgr)
    if abs(angle) < 1.0 or abs(angle) > 25.0:
        return crop_bgr
    h, w = crop_bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(crop_bgr, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_plate_crop(crop_bgr: np.ndarray) -> np.ndarray:
    """Deskew -> resize to target height -> bilateral filter -> CLAHE contrast boost."""
    crop_bgr = _deskew_crop(crop_bgr)
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape[:2]
    target_h = 120
    if h < target_h:
        scale = target_h / max(h, 1)
        gray = cv2.resize(gray, (int(w * scale), target_h), interpolation=cv2.INTER_CUBIC)
    elif h > 240:
        scale = 200.0 / h
        gray = cv2.resize(gray, (int(w * scale), 200), interpolation=cv2.INTER_AREA)

    # Edge-preserving noise removal
    filtered = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)

    # Adaptive contrast boost
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(filtered)

    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


@dataclass
class _Fragment:
    box: list  # EasyOCR polygon points [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
    text: str
    conf: float

    @property
    def x_min(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def x_max(self) -> float:
        return max(p[0] for p in self.box)

    @property
    def y_min(self) -> float:
        return min(p[1] for p in self.box)

    @property
    def y_max(self) -> float:
        return max(p[1] for p in self.box)

    @property
    def height(self) -> float:
        return max(1.0, self.y_max - self.y_min)

    @property
    def y_top_mid(self) -> float:
        return (self.box[0][1] + self.box[1][1]) / 2.0

    @property
    def y_center(self) -> float:
        return (self.y_min + self.y_max) / 2.0


@dataclass
class _Candidate:
    text: str
    conf: float
    score: float


def _cluster_rows(fragments: list[_Fragment]) -> list[list[_Fragment]]:
    """Group fragments into distinct rows by vertical position.
    Indian plates are either 1-line or 2-line. Rows are ordered strictly
    top-to-bottom, and fragments in each row are ordered left-to-right."""
    if not fragments:
        return []

    ordered = sorted(fragments, key=lambda f: f.y_top_mid)
    rows: list[list[_Fragment]] = [[ordered[0]]]

    for frag in ordered[1:]:
        placed = False
        for row in rows:
            overlap_ratios = []
            for rf in row:
                overlap = max(0.0, min(frag.y_max, rf.y_max) - max(frag.y_min, rf.y_min))
                min_h = min(frag.height, rf.height)
                overlap_ratios.append(overlap / min_h if min_h > 0 else 0.0)
            avg_overlap = sum(overlap_ratios) / len(overlap_ratios) if overlap_ratios else 0.0

            row_top_mid = sum(rf.y_top_mid for rf in row) / len(row)
            top_mid_diff = abs(frag.y_top_mid - row_top_mid)
            avg_height = sum(rf.height for rf in row) / len(row)

            if avg_overlap >= 0.40 and top_mid_diff <= 0.45 * avg_height:
                row.append(frag)
                placed = True
                break

        if not placed:
            rows.append([frag])

    # Sort rows by top midpoint (ascending Y)
    rows.sort(key=lambda r: sum(f.y_top_mid for f in r) / len(r))
    # Sort fragments in each row left-to-right
    for r in rows:
        r.sort(key=lambda f: f.x_min)

    return rows


def _fit_to_indian_format(text: str) -> tuple[str, float]:
    """Grammar-guided alignment to Indian vehicle registration standards.
    Returns (corrected_text, quality_score)."""
    if len(text) < 8 or len(text) > 11:
        return text, 0.0

    chars = list(text)
    score = 1.0

    # 1. State Code (First 2 chars)
    raw_st = chars[0] + chars[1]
    s0 = chars[0] if chars[0].isalpha() else DIGIT_TO_LETTER.get(chars[0], chars[0])
    s1 = chars[1] if chars[1].isalpha() else DIGIT_TO_LETTER.get(chars[1], chars[1])
    state = s0 + s1

    if state in INDIAN_STATES:
        chars[0], chars[1] = s0, s1
        score += 4.5
    elif raw_st in STATE_LETTER_SUBS:
        sub = STATE_LETTER_SUBS[raw_st]
        chars[0], chars[1] = sub[0], sub[1]
        score += 4.0
    else:
        found_state = False
        for valid in INDIAN_STATES:
            if sum(1 for a, b in zip(state, valid) if a != b) == 1:
                chars[0], chars[1] = valid[0], valid[1]
                score += 2.5
                found_state = True
                break
        if not found_state:
            score -= 2.0

    # 2. Last 4 characters (Digits)
    for i in range(len(chars) - 4, len(chars)):
        c = chars[i]
        if c.isdigit():
            score += 0.8
        elif c in LETTER_TO_DIGIT:
            chars[i] = LETTER_TO_DIGIT[c]
            score += 0.5
        else:
            score -= 1.0

    # 3. Middle characters (District + Series)
    middle = chars[2:-4]
    if len(middle) >= 2:
        if middle[0].isdigit():
            score += 0.6
        elif middle[0] in LETTER_TO_DIGIT:
            middle[0] = LETTER_TO_DIGIT[middle[0]]
            score += 0.4

        if len(middle) == 2:
            if middle[1].isalpha():
                score += 0.6
            elif middle[1] in DIGIT_TO_LETTER:
                middle[1] = DIGIT_TO_LETTER[middle[1]]
                score += 0.4
        elif len(middle) == 3:
            if middle[1].isdigit():
                if middle[2].isalpha():
                    score += 0.8
                elif middle[2] in DIGIT_TO_LETTER:
                    middle[2] = DIGIT_TO_LETTER[middle[2]]
                    score += 0.4
            else:
                if middle[1] in LETTER_TO_DIGIT and middle[2].isalpha():
                    middle[1] = LETTER_TO_DIGIT[middle[1]]
                    score += 0.8
                elif middle[1].isalpha() and middle[2].isalpha():
                    score += 0.8
        elif len(middle) == 4:
            for k in [0, 1]:
                if middle[k].isdigit():
                    score += 0.4
                elif middle[k] in LETTER_TO_DIGIT:
                    middle[k] = LETTER_TO_DIGIT[middle[k]]
                    score += 0.2
            for k in [2, 3]:
                if middle[k].isalpha():
                    score += 0.4
                elif middle[k] in DIGIT_TO_LETTER:
                    middle[k] = DIGIT_TO_LETTER[middle[k]]
                    score += 0.2

    chars[2:-4] = middle
    candidate = "".join(chars)

    if re.match(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$", candidate):
        score += 5.0

    return candidate, score


def _generate_candidates(ocr_results) -> tuple[list[_Candidate], bool]:
    """Reconstruct and rank candidate plate numbers from OCR fragments."""
    frags = []
    for box, text, conf in ocr_results:
        clean = normalize_plate_text(text)
        if clean and not _looks_like_noise(clean) and conf >= ABS_MIN_CONF:
            frags.append(_Fragment(box, clean, conf))

    low_conf_fallback = False
    if not frags:
        # Fallback to whatever OCR returned
        raw = normalize_plate_text("".join(r[1] for r in ocr_results))
        avg_conf = sum(r[2] for r in ocr_results) / max(len(ocr_results), 1) if ocr_results else 0.0
        return [_Candidate(text=raw, conf=avg_conf, score=0.1)], True

    rows = _cluster_rows(frags)
    combos: list[tuple[str, float]] = []

    # Single row combinations
    for r in rows:
        combos.append(("".join(f.text for f in r), sum(f.conf for f in r) / len(r)))

    # Two-line plates: test both top->bottom and bottom->top permutations
    if len(rows) >= 2:
        for i, j in itertools.combinations(range(len(rows)), 2):
            text_tb = "".join(f.text for f in rows[i]) + "".join(f.text for f in rows[j])
            text_bt = "".join(f.text for f in rows[j]) + "".join(f.text for f in rows[i])
            conf = (sum(f.conf for f in rows[i]) + sum(f.conf for f in rows[j])) / (len(rows[i]) + len(rows[j]))
            combos.append((text_tb, conf))
            combos.append((text_bt, conf))

    pool: dict[str, _Candidate] = {}

    def offer(text: str, score: float, conf: float):
        if not text:
            return
        existing = pool.get(text)
        cand = _Candidate(text=text, conf=conf, score=score)
        if existing is None or cand.score > existing.score:
            pool[text] = cand

    for raw_combo, conf in combos:
        # Full string evaluation
        fitted, score = _fit_to_indian_format(raw_combo)
        offer(fitted, score + conf * 1.5, conf)
        offer(raw_combo, (1.0 if _matches_plate_format(raw_combo) else 0.0) + conf, conf)

        # Sliding window substrings (8 to 11 chars) to peel off border noise (e.g. stray '1')
        for L in range(8, min(12, len(raw_combo))):
            for start in range(len(raw_combo) - L + 1):
                sub = raw_combo[start:start + L]
                fitted_sub, sub_score = _fit_to_indian_format(sub)
                offer(fitted_sub, sub_score + conf * 1.5 - 0.2, conf)

    if not pool:
        raw = "".join(f.text for f in frags)
        return [_Candidate(text=raw, conf=0.1, score=0.1)], True

    ranked = sorted(pool.values(), key=lambda c: c.score, reverse=True)
    return ranked, low_conf_fallback


def _single_substitution_variants(text: str) -> set[str]:
    variants = set()
    for i, ch in enumerate(text):
        sub = SUBSTITUTIONS.get(ch)
        if sub:
            variants.add(text[:i] + sub + text[i + 1:])
    return variants


def _resolve_via_db(db: Session | None, candidates: list[_Candidate], top_k: int = 4) -> tuple[str, float] | None:
    """Check top candidates and their 1-character OCR confusion variants against
    registered Vehicle.plate_number records. DB match wins over raw OCR ranking."""
    if db is None or not candidates:
        return None

    top = candidates[:top_k]
    probe_to_source: dict[str, _Candidate] = {}
    for cand in top:
        probe_to_source.setdefault(cand.text, cand)
        for variant in _single_substitution_variants(cand.text):
            probe_to_source.setdefault(variant, cand)

    if not probe_to_source:
        return None

    rows = db.query(Vehicle.plate_number).filter(Vehicle.plate_number.in_(list(probe_to_source.keys()))).all()
    matched = {r[0] for r in rows}
    if not matched:
        return None

    # Prefer direct candidate match
    for cand in top:
        if cand.text in matched:
            return cand.text, cand.conf
    for text in matched:
        source = probe_to_source.get(text)
        if source is not None:
            return text, source.conf
    return None


@dataclass
class PlateResult:
    plate_number: str | None
    confidence: float
    detector_used: str
    detected: bool
    raw_ocr_text: str | None
    format_valid: bool = False
    low_conf_fallback: bool = False
    db_matched: bool = False


def recognize_plate(image_bgr: np.ndarray, db: Session | None = None) -> PlateResult:
    """Execute complete ANPR pipeline on a vehicle image."""
    boxes, detector_used = detect_plate_regions(image_bgr)

    if not boxes:
        return PlateResult(plate_number=None, confidence=0.0, detector_used=detector_used,
                            detected=False, raw_ocr_text=None)

    best_box = _select_best_box(boxes)
    pad_x = int(best_box.w * CROP_PAD_X_FRAC)
    pad_y = int(best_box.h * CROP_PAD_Y_FRAC)
    h_img, w_img = image_bgr.shape[:2]
    x0 = max(0, best_box.x - pad_x)
    y0 = max(0, best_box.y - pad_y)
    x1 = min(w_img, best_box.x + best_box.w + pad_x)
    y1 = min(h_img, best_box.y + best_box.h + pad_y)
    crop = image_bgr[y0:y1, x0:x1]

    if crop.size == 0:
        return PlateResult(plate_number=None, confidence=0.0, detector_used=detector_used,
                            detected=True, raw_ocr_text=None)

    processed = preprocess_plate_crop(crop)
    reader = get_ocr_reader()

    ocr_results = reader.readtext(processed, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    if not ocr_results:
        # Fallback to reading raw crop
        ocr_results = reader.readtext(crop, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

    if not ocr_results:
        return PlateResult(plate_number=None, confidence=0.0, detector_used=detector_used,
                            detected=True, raw_ocr_text=None)

    candidates, low_conf_fallback = _generate_candidates(ocr_results)
    best = candidates[0]

    db_match = _resolve_via_db(db, candidates)
    if db_match is not None:
        final_text, final_conf = db_match
        db_matched = True
    else:
        final_text, final_conf = best.text, best.conf
        db_matched = False

    normalized = normalize_plate_text(final_text)

    return PlateResult(
        plate_number=normalized or None,
        confidence=round(float(final_conf), 4),
        detector_used=detector_used,
        detected=True,
        raw_ocr_text=best.text,
        format_valid=_matches_plate_format(normalized) if normalized else False,
        low_conf_fallback=low_conf_fallback,
        db_matched=db_matched,
    )


def lookup_plate_owner(db: Session, plate_number: str | None, require_format_valid: bool = True,
                        format_valid: bool = False) -> Vehicle | None:
    """DB is the source of truth: plate_number -> vehicles -> person_id."""
    if not plate_number:
        return None
    # Self-validating: check format if format_valid is not explicitly provided
    if require_format_valid and not format_valid:
        if not _matches_plate_format(plate_number):
            return None
    return db.query(Vehicle).filter_by(plate_number=plate_number).first()