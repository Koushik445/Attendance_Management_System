from pydantic import BaseModel


class StatusCounts(BaseModel):
    persons: int
    vehicles: int
    id_cards: int
    recognition_events: int
    attendance_events: int


class SystemStatusOut(BaseModel):
    environment: str
    face_model_loaded: bool
    arrival_model_loaded: bool
    plate_detector_type: str
    counts: StatusCounts
    face_evaluation: dict | None = None
    anpr_evaluation: dict | None = None
