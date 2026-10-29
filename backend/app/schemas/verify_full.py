from pydantic import BaseModel


class FaceEvidenceOut(BaseModel):
    person_id: int | None = None
    person_name: str | None = None
    similarity: float
    confidence_label: str


class PlateEvidenceOut(BaseModel):
    plate_number: str | None = None
    person_id: int | None = None
    person_name: str | None = None
    confidence: float
    detector_used: str | None = None


class IdCardEvidenceOut(BaseModel):
    person_id: int | None = None
    person_name: str | None = None
    status: str
    confidence: float


class ArrivalOut(BaseModel):
    arrival_type: str
    source: str  # "manual" or "auto_detected"
    confidence: float
    reason: str | None = None


class VerifyFullResponse(BaseModel):
    recognition_event_id: int
    arrival: ArrivalOut

    face: FaceEvidenceOut | None = None
    plate: PlateEvidenceOut | None = None
    id_card: IdCardEvidenceOut | None = None

    person_id: int | None = None
    person_name: str | None = None
    employee_id: str | None = None

    final_confidence: float
    decision: str
    verification_method: str
    requires_additional_verification: bool
    reason: str

    attendance_recorded: bool
    attendance_event_id: int | None = None
    event_type: str = "ENTRY"
    campus_duration: str | None = None
    campus_duration_seconds: int | None = None

