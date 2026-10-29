"""
Verification endpoints.

  POST /api/verify/face      - face-only (used standalone for debugging/UI quick-check)
  POST /api/verify/vehicle   - plate-only (used standalone for debugging/UI quick-check)
  POST /api/verify/id-card   - ID OCR-text lookup (used standalone for debugging/UI quick-check)
  POST /api/verify           - THE main endpoint: route-aware, arrival-type-aware,
                                minimum-necessary-evidence fusion. This is what the
                                frontend's Verify Attendance page calls.
"""
import json
from datetime import datetime, timezone

import cv2
import numpy as np
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    Person, RecognitionEvent, AttendanceEvent,
    ArrivalType, DecisionStatus, AttendanceEventType,
)
from app.schemas.verify import FaceVerifyResponse
from app.schemas.verify_full import (
    VerifyFullResponse, FaceEvidenceOut, PlateEvidenceOut, IdCardEvidenceOut, ArrivalOut,
)
from app.services.face_service import extract_embedding, recognize_embedding
from app.services.anpr_service import recognize_plate, lookup_plate_owner
from app.services.id_card_service import verify_id_text
from app.services.arrival_service import detect_arrival_type
from app.services.fusion_service import run_fusion

router = APIRouter(prefix="/verify", tags=["verify"])


def _read_upload_as_bgr(upload: UploadFile) -> np.ndarray:
    data = upload.file.read()
    array = np.frombuffer(data, dtype=np.uint8)
    image_bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise HTTPException(status_code=400, detail="Could not decode image. Upload a valid JPEG/PNG.")
    return image_bgr


# ---------------------------------------------------------------------------
# Single-modality endpoints (standalone debugging / building-block testing)
# ---------------------------------------------------------------------------

@router.post("/face", response_model=FaceVerifyResponse)
def verify_face(file: UploadFile = File(...), db: Session = Depends(get_db)):
    image_bgr = _read_upload_as_bgr(file)
    extraction = extract_embedding(image_bgr)
    if extraction.embedding is None:
        return FaceVerifyResponse(faces_detected=0, person_id=None, person_name=None,
                                   employee_id=None, similarity=0.0, confidence_label="LOW")

    match = recognize_embedding(db, extraction.embedding)
    employee_id = None
    if match.person_id:
        person = db.query(Person).filter_by(id=match.person_id).first()
        employee_id = person.employee_id if person else None

    return FaceVerifyResponse(
        faces_detected=extraction.num_faces_detected, person_id=match.person_id,
        person_name=match.person_name, employee_id=employee_id,
        similarity=match.similarity, confidence_label=match.confidence_label,
    )


@router.post("/vehicle")
def verify_vehicle(file: UploadFile = File(...), db: Session = Depends(get_db)):
    image_bgr = _read_upload_as_bgr(file)
    plate = recognize_plate(image_bgr, db=db)
    vehicle = lookup_plate_owner(db, plate.plate_number, format_valid=plate.format_valid)
    person = db.query(Person).filter_by(id=vehicle.person_id).first() if vehicle else None

    return {
        "plate_number": plate.plate_number,
        "detected": plate.detected,
        "detector_used": plate.detector_used,
        "confidence": plate.confidence,
        "person_id": person.id if person else None,
        "person_name": person.name if person else None,
    }


@router.post("/id-card")
def verify_id_card(ocr_text: str = Form(...), db: Session = Depends(get_db)):
    match = verify_id_text(db, ocr_text)
    return {
        "status": match.status,
        "person_id": match.person_id,
        "person_name": match.person_name,
        "employee_id": match.employee_id,
        "confidence": match.confidence,
    }


# ---------------------------------------------------------------------------
# Combined, route-aware verification (the main endpoint)
# ---------------------------------------------------------------------------

@router.post("", response_model=VerifyFullResponse)
def verify(
    arrival_type: str = Form("AUTO"),  # "AUTO" | "WALKING" | "CAR" | "BIKE"
    event_type: str = Form("AUTO"),    # "AUTO" | "ENTRY" | "EXIT"
    face_image: UploadFile | None = File(None),
    vehicle_image: UploadFile | None = File(None),
    id_card_text: str | None = Form(None),
    db: Session = Depends(get_db),
):
    face_bgr = _read_upload_as_bgr(face_image) if face_image is not None else None
    vehicle_bgr = _read_upload_as_bgr(vehicle_image) if vehicle_image is not None else None

    # --- 1. Resolve arrival type ---
    if arrival_type in ("WALKING", "CAR", "BIKE"):
        resolved_arrival = arrival_type
        arrival_source = "manual"
        arrival_confidence = 1.0
        arrival_reason = "Manually selected by user."
    else:
        scene_image = vehicle_bgr if vehicle_bgr is not None else face_bgr
        if scene_image is None:
            raise HTTPException(status_code=400, detail="Provide at least one image for AUTO arrival detection, "
                                                          "or select an arrival type manually.")
        detection = detect_arrival_type(scene_image)
        resolved_arrival = detection.arrival_type if detection.arrival_type != "UNKNOWN" else "WALKING"
        arrival_source = "auto_detected"
        arrival_confidence = detection.confidence
        arrival_reason = detection.reason

    # --- 2. Validate required inputs for the resolved route ---
    if face_bgr is None:
        raise HTTPException(status_code=400, detail="face_image is required for verification.")
    if resolved_arrival in ("CAR", "BIKE") and vehicle_bgr is None:
        raise HTTPException(status_code=400,
                             detail=f"vehicle_image is required for arrival_type={resolved_arrival}.")

    # --- 3. Gather evidence ---
    face_extraction = extract_embedding(face_bgr)
    if face_extraction.embedding is not None:
        face_match = recognize_embedding(db, face_extraction.embedding)
        face_evidence = {
            "person_id": face_match.person_id,
            "similarity": face_match.similarity,
            "confidence": face_match.similarity,
        }
        face_out = FaceEvidenceOut(
            person_id=face_match.person_id, person_name=face_match.person_name,
            similarity=face_match.similarity, confidence_label=face_match.confidence_label,
        )
    else:
        face_evidence = None
        face_out = FaceEvidenceOut(person_id=None, person_name=None, similarity=0.0, confidence_label="LOW")

    plate_evidence = None
    plate_out = None
    if resolved_arrival in ("CAR", "BIKE") and vehicle_bgr is not None:
        plate_result = recognize_plate(vehicle_bgr, db=db)
        vehicle_row = lookup_plate_owner(db, plate_result.plate_number, format_valid=plate_result.format_valid)
        plate_person = db.query(Person).filter_by(id=vehicle_row.person_id).first() if vehicle_row else None
        plate_evidence = {
            "person_id": plate_person.id if plate_person else None,
            "plate_number": plate_result.plate_number,
            "confidence": plate_result.confidence,
        }
        plate_out = PlateEvidenceOut(
            plate_number=plate_result.plate_number,
            person_id=plate_person.id if plate_person else None,
            person_name=plate_person.name if plate_person else None,
            confidence=plate_result.confidence,
            detector_used=plate_result.detector_used,
        )

    id_card_evidence = None
    id_card_out = None
    if id_card_text:
        id_match = verify_id_text(db, id_card_text)
        id_card_evidence = {"person_id": id_match.person_id, "confidence": id_match.confidence}
        id_card_out = IdCardEvidenceOut(
            person_id=id_match.person_id, person_name=id_match.person_name,
            status=id_match.status, confidence=id_match.confidence,
        )

    # --- 4. Fusion decision (pure function, no ML/DB knowledge) ---
    decision_result = run_fusion({
        "arrival_type": resolved_arrival,
        "face": face_evidence,
        "plate": plate_evidence,
        "id_card": id_card_evidence,
    })

    final_person = None
    if decision_result["person_id"]:
        final_person = db.query(Person).filter_by(id=decision_result["person_id"]).first()

    # --- 5. Persist recognition event (always logged, success or failure) ---
    recognition_event = RecognitionEvent(
        arrival_type=ArrivalType(resolved_arrival),
        face_person_id=face_evidence["person_id"] if face_evidence else None,
        face_similarity=face_evidence["similarity"] if face_evidence else None,
        face_confidence=face_evidence["confidence"] if face_evidence else None,
        plate_number=plate_evidence["plate_number"] if plate_evidence else None,
        plate_person_id=plate_evidence["person_id"] if plate_evidence else None,
        plate_confidence=plate_evidence["confidence"] if plate_evidence else None,
        id_card_person_id=id_card_evidence["person_id"] if id_card_evidence else None,
        id_card_confidence=id_card_evidence["confidence"] if id_card_evidence else None,
        final_person_id=decision_result["person_id"],
        final_confidence=decision_result["final_confidence"],
        decision=DecisionStatus(decision_result["decision"]),
        verification_method=decision_result["verification_method"],
        event_metadata=json.dumps({
            "arrival_source": arrival_source,
            "arrival_reason": arrival_reason,
            "fusion_reason": decision_result["reason"],
            "event_type_requested": event_type,
        }),
    )
    db.add(recognition_event)
    db.flush()

    # --- 6. Attendance recording with ENTRY/EXIT and Campus Duration ---
    attendance_event_id = None
    resolved_event_type = AttendanceEventType.ENTRY
    campus_duration_str = None
    campus_duration_secs = None

    if decision_result["decision"] == "VERIFIED" and decision_result["person_id"]:
        pid = decision_result["person_id"]
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(datetime.now().date(), datetime.min.time())

        # Determine ENTRY vs EXIT
        if event_type.upper() in ("ENTRY", "EXIT"):
            resolved_event_type = AttendanceEventType(event_type.upper())
        else:
            # AUTO logic: check latest attendance event for this person today
            latest_ev = (
                db.query(AttendanceEvent)
                .filter(AttendanceEvent.person_id == pid, AttendanceEvent.timestamp >= today_start)
                .order_by(AttendanceEvent.timestamp.desc())
                .first()
            )
            if latest_ev and latest_ev.event_type == AttendanceEventType.ENTRY:
                resolved_event_type = AttendanceEventType.EXIT
            else:
                resolved_event_type = AttendanceEventType.ENTRY

        # Duration Calculation on EXIT
        if resolved_event_type == AttendanceEventType.EXIT:
            matching_entry = (
                db.query(AttendanceEvent)
                .filter(
                    AttendanceEvent.person_id == pid,
                    AttendanceEvent.event_type == AttendanceEventType.ENTRY,
                    AttendanceEvent.timestamp >= today_start,
                )
                .order_by(AttendanceEvent.timestamp.desc())
                .first()
            )
            if matching_entry and matching_entry.timestamp:
                entry_ts = matching_entry.timestamp
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(tzinfo=timezone.utc)
                diff = now - entry_ts
                campus_duration_secs = max(0, int(diff.total_seconds()))
                hours = campus_duration_secs // 3600
                mins = (campus_duration_secs % 3600) // 60
                secs = campus_duration_secs % 60
                if hours > 0:
                    campus_duration_str = f"{hours}h {mins}m"
                elif mins > 0:
                    campus_duration_str = f"{mins}m {secs}s"
                else:
                    campus_duration_str = f"{secs}s"

        attendance_event = AttendanceEvent(
            person_id=pid,
            event_type=resolved_event_type,
            verification_method=decision_result["verification_method"],
            confidence=decision_result["final_confidence"],
            recognition_event_id=recognition_event.id,
        )
        db.add(attendance_event)
        db.flush()
        attendance_event_id = attendance_event.id

    db.commit()

    return VerifyFullResponse(
        recognition_event_id=recognition_event.id,
        arrival=ArrivalOut(arrival_type=resolved_arrival, source=arrival_source,
                            confidence=arrival_confidence, reason=arrival_reason),
        face=face_out,
        plate=plate_out,
        id_card=id_card_out,
        person_id=final_person.id if final_person else None,
        person_name=final_person.name if final_person else None,
        employee_id=final_person.employee_id if final_person else None,
        final_confidence=decision_result["final_confidence"],
        decision=decision_result["decision"],
        verification_method=decision_result["verification_method"],
        requires_additional_verification=decision_result["requires_additional_verification"],
        reason=decision_result["reason"],
        attendance_recorded=attendance_event_id is not None,
        attendance_event_id=attendance_event_id,
        event_type=resolved_event_type.value,
        campus_duration=campus_duration_str,
        campus_duration_seconds=campus_duration_secs,
    )

