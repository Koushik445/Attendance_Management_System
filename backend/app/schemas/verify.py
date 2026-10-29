from pydantic import BaseModel


class FaceVerifyResponse(BaseModel):
    faces_detected: int
    person_id: int | None
    person_name: str | None
    employee_id: str | None
    similarity: float
    confidence_label: str  # HIGH / MEDIUM / LOW
