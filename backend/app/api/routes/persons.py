import os
import re
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Person, FaceEmbedding, Vehicle, IDCard, PersonStatus, VehicleStatus
from app.schemas.person import PersonOut
from app.services.face_service import extract_embedding
from app.services.anpr_service import normalize_plate_text

router = APIRouter(prefix="/persons", tags=["persons"])


@router.get("", response_model=list[PersonOut])
def list_persons(db: Session = Depends(get_db)):
    return db.query(Person).order_by(Person.id).all()


@router.get("/{person_id}", response_model=PersonOut)
def get_person(person_id: int, db: Session = Depends(get_db)):
    person = db.query(Person).filter_by(id=person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@router.post("/enroll")
def enroll_person(
    name: str = Form(...),
    employee_id: str = Form(...),
    department: str | None = Form(None),
    plate_number: str | None = Form(None),
    vehicle_type: str | None = Form("CAR"),
    id_card_number: str | None = Form(None),
    face_image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # 1. Clean inputs
    name = name.strip()
    employee_id = employee_id.strip()
    department = department.strip() if department else None

    if not name or not employee_id:
        raise HTTPException(status_code=400, detail="Name and Employee ID are required.")

    # Check for existing employee_id
    if db.query(Person).filter_by(employee_id=employee_id).first():
        raise HTTPException(status_code=400, detail=f"Employee ID '{employee_id}' is already registered.")

    # 2. Decode face image
    data = face_image.file.read()
    array = np.frombuffer(data, dtype=np.uint8)
    image_bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise HTTPException(status_code=400, detail="Could not decode face image. Please upload a valid JPEG/PNG.")

    # 3. Extract face embedding
    extraction = extract_embedding(image_bgr)
    if extraction.embedding is None:
        raise HTTPException(status_code=400, detail="No face detected in the photo. Please ensure face is centered and well-lit.")

    # 4. Save face photo to disk
    upload_dir = os.path.join("datasets", "enrollments", employee_id)
    os.makedirs(upload_dir, exist_ok=True)
    saved_img_path = os.path.join(upload_dir, "face_1.jpg")
    cv2.imwrite(saved_img_path, image_bgr)

    # 5. Create Person
    person = Person(
        name=name,
        employee_id=employee_id,
        department=department,
    )
    db.add(person)
    db.flush()

    # 6. Save FaceEmbedding
    face_embedding = FaceEmbedding(
        person_id=person.id,
        embedding=extraction.embedding.tolist(),
        image_path=saved_img_path,
    )
    db.add(face_embedding)

    # 7. Optional Vehicle
    created_vehicle = None
    if plate_number and plate_number.strip():
        norm_plate = normalize_plate_text(plate_number.strip())
        existing_v = db.query(Vehicle).filter_by(plate_number=norm_plate).first()
        if existing_v:
            raise HTTPException(status_code=400, detail=f"Plate number '{norm_plate}' is already assigned to person #{existing_v.person_id}.")
        created_vehicle = Vehicle(
            person_id=person.id,
            plate_number=norm_plate,
            vehicle_type=(vehicle_type or "CAR").upper(),
        )
        db.add(created_vehicle)

    # 8. Optional ID Card
    created_card = None
    card_num = id_card_number.strip() if id_card_number and id_card_number.strip() else employee_id
    if card_num:
        norm_card = re.sub(r"[^A-Z0-9]", "", card_num.upper())
        existing_card = db.query(IDCard).filter_by(card_number=norm_card).first()
        if existing_card:
            raise HTTPException(status_code=400, detail=f"ID Card '{norm_card}' is already assigned to person #{existing_card.person_id}.")
        created_card = IDCard(
            person_id=person.id,
            card_number=norm_card,
        )
        db.add(created_card)

    db.commit()

    return {
        "success": True,
        "message": f"Successfully enrolled {person.name} ({person.employee_id})",
        "person": {
            "id": person.id,
            "name": person.name,
            "employee_id": person.employee_id,
            "department": person.department,
        },
        "faces_detected": extraction.num_faces_detected,
        "face_det_score": round(extraction.det_score or 0.0, 3),
        "plate_number": created_vehicle.plate_number if created_vehicle else None,
        "id_card_number": created_card.card_number if created_card else None,
    }


@router.delete("/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db)):
    person = db.query(Person).filter_by(id=person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    db.delete(person)
    db.commit()
    return {"success": True, "message": f"Person #{person_id} deleted."}


@router.put("/{person_id}")
def update_person(
    person_id: int,
    name: str = Form(...),
    employee_id: str = Form(...),
    department: str | None = Form(None),
    status: str | None = Form("ACTIVE"),
    plate_number: str | None = Form(None),
    vehicle_type: str | None = Form("CAR"),
    id_card_number: str | None = Form(None),
    face_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    person = db.query(Person).filter_by(id=person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    name = name.strip()
    employee_id = employee_id.strip()
    department = department.strip() if department else None

    if not name or not employee_id:
        raise HTTPException(status_code=400, detail="Name and Employee ID cannot be empty.")

    # Check unique employee_id against other people
    existing_emp = db.query(Person).filter(Person.employee_id == employee_id, Person.id != person_id).first()
    if existing_emp:
        raise HTTPException(status_code=400, detail=f"Employee ID '{employee_id}' is already registered to another person.")

    person.name = name
    person.employee_id = employee_id
    person.department = department
    if status:
        person.status = PersonStatus.ACTIVE if status.upper() == "ACTIVE" else PersonStatus.INACTIVE

    # Handle vehicle plate number update
    if plate_number is not None:
        clean_plate = plate_number.strip()
        if clean_plate:
            norm_plate = normalize_plate_text(clean_plate)
            existing_v = db.query(Vehicle).filter(Vehicle.plate_number == norm_plate, Vehicle.person_id != person_id).first()
            if existing_v:
                raise HTTPException(status_code=400, detail=f"Plate number '{norm_plate}' is already assigned to person #{existing_v.person_id}.")
            
            if person.vehicles:
                v = person.vehicles[0]
                v.plate_number = norm_plate
                v.vehicle_type = (vehicle_type or "CAR").upper()
                v.status = VehicleStatus.ACTIVE
            else:
                db.add(Vehicle(person_id=person.id, plate_number=norm_plate, vehicle_type=(vehicle_type or "CAR").upper(), status=VehicleStatus.ACTIVE))
        else:
            for v in person.vehicles:
                db.delete(v)

    # Handle ID card number update
    card_val = id_card_number.strip() if id_card_number is not None else None
    if card_val is not None:
        if card_val:
            norm_card = re.sub(r"[^A-Z0-9]", "", card_val.upper())
            existing_c = db.query(IDCard).filter(IDCard.card_number == norm_card, IDCard.person_id != person_id).first()
            if existing_c:
                raise HTTPException(status_code=400, detail=f"ID Card '{norm_card}' is already assigned to person #{existing_c.person_id}.")
            if person.id_cards:
                person.id_cards[0].card_number = norm_card
                person.id_cards[0].status = PersonStatus.ACTIVE
            else:
                db.add(IDCard(person_id=person.id, card_number=norm_card))
        else:
            for c in person.id_cards:
                db.delete(c)

    # Handle Face Image update if uploaded
    faces_detected = None
    if face_image is not None and getattr(face_image, "filename", None):
        data = face_image.file.read()
        if data:
            array = np.frombuffer(data, dtype=np.uint8)
            image_bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if image_bgr is None:
                raise HTTPException(status_code=400, detail="Could not decode uploaded face photo.")
            extraction = extract_embedding(image_bgr)
            if extraction.embedding is None:
                raise HTTPException(status_code=400, detail="No face detected in the uploaded photo. Please provide a clear frontal photo.")
            faces_detected = extraction.num_faces_detected
            upload_dir = os.path.join("datasets", "enrollments", employee_id)
            os.makedirs(upload_dir, exist_ok=True)
            saved_img_path = os.path.join(upload_dir, "face_1.jpg")
            cv2.imwrite(saved_img_path, image_bgr)

            if person.face_embeddings:
                person.face_embeddings[0].embedding = extraction.embedding.tolist()
                person.face_embeddings[0].image_path = saved_img_path
            else:
                db.add(FaceEmbedding(person_id=person.id, embedding=extraction.embedding.tolist(), image_path=saved_img_path))

    db.commit()
    db.refresh(person)

    return {
        "success": True,
        "message": f"Successfully updated {person.name} ({person.employee_id})",
        "person": {
            "id": person.id,
            "name": person.name,
            "employee_id": person.employee_id,
            "department": person.department,
            "status": person.status,
            "vehicles": [{"id": v.id, "plate_number": v.plate_number, "vehicle_type": v.vehicle_type} for v in person.vehicles],
            "id_cards": [{"id": c.id, "card_number": c.card_number} for c in person.id_cards],
        },
        "faces_detected": faces_detected,
    }

