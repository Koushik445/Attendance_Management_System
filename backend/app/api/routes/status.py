import json
import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings, PROJECT_ROOT
from app.db.database import get_db
from app.db.models import Person, Vehicle, IDCard, RecognitionEvent, AttendanceEvent
from app.schemas.status import SystemStatusOut, StatusCounts

router = APIRouter(prefix="/status", tags=["status"])


def _read_json_if_exists(path: str):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


@router.get("", response_model=SystemStatusOut)
def get_status(db: Session = Depends(get_db)):
    # Check model-load status without forcing a load (avoid slow /status calls).
    from app.services import face_service, arrival_service

    face_loaded = face_service._face_app is not None
    arrival_loaded = arrival_service._yolo_model is not None

    from app.services import anpr_service
    if anpr_service._yolo_plate_model is not None:
        plate_detector_type = "yolo"
    elif os.path.isfile(settings.PLATE_DETECTOR_MODEL_PATH):
        plate_detector_type = "yolo (not yet loaded)"
    else:
        plate_detector_type = "haar_fallback (no YOLO plate weights configured)"

    counts = StatusCounts(
        persons=db.query(Person).count(),
        vehicles=db.query(Vehicle).count(),
        id_cards=db.query(IDCard).count(),
        recognition_events=db.query(RecognitionEvent).count(),
        attendance_events=db.query(AttendanceEvent).count(),
    )

    face_eval = _read_json_if_exists(os.path.join(PROJECT_ROOT, "results", "face_summary.json"))
    anpr_eval = _read_json_if_exists(os.path.join(PROJECT_ROOT, "results", "anpr_summary.json"))

    return SystemStatusOut(
        environment=settings.ENVIRONMENT,
        face_model_loaded=face_loaded,
        arrival_model_loaded=arrival_loaded,
        plate_detector_type=plate_detector_type,
        counts=counts,
        face_evaluation=face_eval,
        anpr_evaluation=anpr_eval,
    )
