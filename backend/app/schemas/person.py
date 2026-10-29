from datetime import datetime
from pydantic import BaseModel


class VehicleBrief(BaseModel):
    id: int
    plate_number: str
    vehicle_type: str | None = None
    status: str

    model_config = {"from_attributes": True}


class IDCardBrief(BaseModel):
    id: int
    card_number: str
    status: str

    model_config = {"from_attributes": True}


class PersonOut(BaseModel):
    id: int
    employee_id: str
    name: str
    department: str | None = None
    status: str
    created_at: datetime
    vehicles: list[VehicleBrief] = []
    id_cards: list[IDCardBrief] = []

    model_config = {"from_attributes": True}

