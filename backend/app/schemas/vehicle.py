from datetime import datetime
from pydantic import BaseModel


class VehicleOut(BaseModel):
    id: int
    person_id: int
    plate_number: str
    vehicle_type: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
