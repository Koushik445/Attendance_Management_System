"""
Route-specific fusion / decision engine.

CONTRACT
--------
This module receives ONLY structured evidence that has already been
resolved to person_id by the ML/service layer - it never sees images,
embeddings, or OCR internals, and it never imports anything from the
backend app or ML packages. This keeps it independently testable and
guarantees the "database is the source of truth for identity" principle:
by the time evidence reaches here, every modality has already been turned
into a person_id via a DB lookup upstream.

Input shape:
{
    "arrival_type": "WALKING" | "CAR" | "BIKE",
    "face":    {"person_id": int|None, "similarity": float, "confidence": float} | None,
    "plate":   {"person_id": int|None, "plate_number": str|None, "confidence": float} | None,
    "id_card": {"person_id": int|None, "confidence": float} | None,
}

Output shape:
{
    "person_id": int | None,
    "final_confidence": float,
    "decision": "VERIFIED" | "NEEDS_ID" | "REJECTED" | "MANUAL_REVIEW" | "UNKNOWN",
    "verification_method": str,           # e.g. "FACE", "FACE+PLATE", "FACE+PLATE+ID"
    "requires_additional_verification": bool,
    "reason": str,
}

Policy summary (see project spec for the full table):
  WALKING:      face HIGH -> VERIFIED. face MEDIUM/LOW -> request ID. face+ID
                agree -> VERIFIED. disagree -> MANUAL_REVIEW.
  CAR / BIKE:   face+plate agree with sufficient confidence -> VERIFIED.
                insufficient or conflicting -> request ID. face+plate+ID:
                agree -> VERIFIED, else -> MANUAL_REVIEW/REJECTED.
  Never automatically mark attendance when evidence conflicts, and never
  require more modalities than necessary for a confident decision.
"""

DEFAULT_THRESHOLDS = {
    "face_high": 0.55,
    "face_low": 0.35,
    "plate_high": 0.85,
    "plate_low": 0.55,
}


def _face_level(face, t):
    if not face or face.get("person_id") is None:
        return "NONE"
    sim = face.get("similarity", 0.0)
    if sim >= t["face_high"]:
        return "HIGH"
    if sim >= t["face_low"]:
        return "MEDIUM"
    return "LOW"


def _plate_level(plate, t):
    if not plate or plate.get("person_id") is None:
        return "NONE"
    conf = plate.get("confidence", 0.0)
    if conf >= t["plate_high"]:
        return "HIGH"
    if conf >= t["plate_low"]:
        return "MEDIUM"
    return "LOW"


def _agree(*person_ids):
    """True if all non-None person_ids among the given values are equal
    (vacuously true if 0 or 1 modalities have an opinion)."""
    known = [p for p in person_ids if p is not None]
    if len(known) <= 1:
        return True
    return len(set(known)) == 1


def _result(person_id, confidence, decision, method, requires_id, reason):
    return {
        "person_id": person_id,
        "final_confidence": round(float(confidence), 4),
        "decision": decision,
        "verification_method": method,
        "requires_additional_verification": requires_id,
        "reason": reason,
    }


def decide(evidence: dict, thresholds: dict | None = None) -> dict:
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    arrival_type = evidence.get("arrival_type", "WALKING")
    face = evidence.get("face")
    plate = evidence.get("plate")
    id_card = evidence.get("id_card")

    if arrival_type == "WALKING":
        return _decide_walking(face, id_card, t)
    return _decide_vehicle(face, plate, id_card, t)


def _decide_walking(face, id_card, t):
    face_level = _face_level(face, t)
    face_pid = face.get("person_id") if face else None

    if face_level == "HIGH":
        return _result(face_pid, face["confidence"], "VERIFIED", "FACE",
                        False, "Face confidence HIGH - no ID required.")

    if id_card is None:
        if face_level in ("MEDIUM", "LOW"):
            return _result(None, face.get("confidence", 0.0), "NEEDS_ID", "FACE",
                            True, "Face confidence insufficient - ID card required.")
        return _result(None, 0.0, "NEEDS_ID", "FACE", True,
                        "No confident face match - ID card required.")

    # We now have id_card evidence too.
    id_pid = id_card.get("person_id")
    id_conf = id_card.get("confidence", 0.0)

    if id_pid is None:
        if face_pid is not None:
            return _result(None, 0.0, "MANUAL_REVIEW", "FACE+ID", False,
                            "Face gave a low-confidence match but ID card matched no record.")
        return _result(None, 0.0, "REJECTED", "FACE+ID", False,
                        "Neither face nor ID card matched a known person.")

    if face_pid is not None and face_pid != id_pid:
        return _result(None, 0.0, "MANUAL_REVIEW", "FACE+ID", False,
                        f"Identity conflict: face -> person {face_pid}, ID card -> person {id_pid}.")

    final_conf = max(face.get("confidence", 0.0) if face else 0.0, id_conf)
    return _result(id_pid, final_conf, "VERIFIED", "FACE+ID", False,
                    "Face and ID card evidence agree.")


def _decide_vehicle(face, plate, id_card, t):
    face_level = _face_level(face, t)
    plate_level = _plate_level(plate, t)
    face_pid = face.get("person_id") if face else None
    plate_pid = plate.get("person_id") if plate else None

    conflict = not _agree(face_pid, plate_pid)
    both_present = face_level != "NONE" and plate_level != "NONE"
    strong_enough = {face_level, plate_level} <= {"HIGH", "MEDIUM"}

    if not conflict and both_present and strong_enough:
        pid = face_pid or plate_pid
        conf = min(face["confidence"], plate["confidence"])
        return _result(pid, conf, "VERIFIED", "FACE+PLATE", False,
                        f"Face ({face_level}) and plate ({plate_level}) agree with sufficient confidence.")

    if id_card is None:
        reason = ("Face/plate identity conflict - ID required." if conflict
                  else "Face/plate confidence insufficient or a modality is missing - ID required.")
        return _result(None, 0.0, "NEEDS_ID", "FACE+PLATE", True, reason)

    # Combine all three.
    id_pid = id_card.get("person_id")
    id_conf = id_card.get("confidence", 0.0)
    known_pids = [p for p in (face_pid, plate_pid, id_pid) if p is not None]

    if not known_pids:
        return _result(None, 0.0, "REJECTED", "FACE+PLATE+ID", False,
                        "No modality (face, plate, or ID) matched a known person.")

    if len(set(known_pids)) > 1:
        return _result(None, 0.0, "MANUAL_REVIEW", "FACE+PLATE+ID", False,
                        f"All-modality identity conflict: face={face_pid}, plate={plate_pid}, id={id_pid}.")

    pid = known_pids[0]
    confs = [c for c in [
        face.get("confidence") if face else None,
        plate.get("confidence") if plate else None,
        id_conf,
    ] if c is not None]
    return _result(pid, max(confs) if confs else 0.0, "VERIFIED", "FACE+PLATE+ID", False,
                    "Face, plate, and ID card evidence agree.")
