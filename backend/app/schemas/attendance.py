from datetime import datetime
from pydantic import BaseModel


class AttendanceEventOut(BaseModel):
    id: int
    person_id: int
    person_name: str | None = None
    employee_id: str | None = None
    department: str | None = None
    event_type: str
    timestamp: datetime
    verification_method: str | None = None
    confidence: float | None = None
    recognition_event_id: int | None = None
    duration_text: str | None = None

    model_config = {"from_attributes": True}


class RecognitionEventOut(BaseModel):
    id: int
    timestamp: datetime
    arrival_type: str

    face_person_id: int | None = None
    face_similarity: float | None = None
    face_confidence: float | None = None

    plate_number: str | None = None
    plate_person_id: int | None = None
    plate_confidence: float | None = None

    id_card_person_id: int | None = None
    id_card_confidence: float | None = None

    final_person_id: int | None = None
    final_confidence: float | None = None

    decision: str
    verification_method: str | None = None

    model_config = {"from_attributes": True}
