"""
Demo database admin operations (seed / clear), factored out so both the CLI
scripts (scripts/seed_demo_database.py, scripts/clear_demo_database.py) and
the POST /api/admin/seed-demo, /api/admin/clear-demo endpoints share one
implementation instead of duplicating logic.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal, engine, Base
from app.db.models import (
    Person, Vehicle, IDCard, PersonStatus, VehicleStatus,
    AttendanceEvent, RecognitionEvent, FaceEmbedding,
)


def discover_people(train_dir: str) -> list[str]:
    if not os.path.isdir(train_dir):
        return []
    return sorted(
        d for d in os.listdir(train_dir)
        if os.path.isdir(os.path.join(train_dir, d)) and not d.startswith(".")
    )


def _read_text_file(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    return content or None


def seed_demo(dry_run: bool = False) -> dict:
    """Populate persons/vehicles/id_cards from the dataset folder structure.
    No names/plates/IDs are hard-coded - everything comes from the dataset
    on disk (see settings.face_train_path / face_test_path)."""
    train_dir = settings.face_train_path
    test_dir = settings.face_test_path

    people = discover_people(train_dir)
    log: list[str] = [f"Discovered {len(people)} demo people in {train_dir}"]

    if not people:
        return {"ok": False, "log": log + ["No people discovered - check dataset path."]}

    if not dry_run:
        Base.metadata.create_all(bind=engine)

    db: Session | None = SessionLocal() if not dry_run else None
    counts = {"persons_created": 0, "persons_skipped": 0,
              "vehicles_created": 0, "vehicles_skipped": 0,
              "id_cards_created": 0, "id_cards_skipped": 0}

    try:
        for idx, name in enumerate(people, start=1):
            employee_id = f"DEMO{idx:03d}"
            person_test_dir = os.path.join(test_dir, name)

            if dry_run:
                log.append(f"[DRY-RUN] person {employee_id} -> {name}")
                counts["persons_created"] += 1
                person = None
            else:
                person = db.query(Person).filter_by(employee_id=employee_id).first()
                if person:
                    counts["persons_skipped"] += 1
                else:
                    person = Person(employee_id=employee_id, name=name, status=PersonStatus.ACTIVE)
                    db.add(person)
                    db.flush()
                    counts["persons_created"] += 1
                log.append(f"person {employee_id} -> {name} (id={person.id})")

            plate_number = _read_text_file(os.path.join(person_test_dir, f"car_number_{name}.txt"))
            if plate_number:
                plate_number = plate_number.upper().replace(" ", "")
                if dry_run:
                    counts["vehicles_created"] += 1
                else:
                    if db.query(Vehicle).filter_by(plate_number=plate_number).first():
                        counts["vehicles_skipped"] += 1
                    else:
                        db.add(Vehicle(person_id=person.id, plate_number=plate_number,
                                        vehicle_type="CAR", status=VehicleStatus.ACTIVE))
                        counts["vehicles_created"] += 1

            card_number = _read_text_file(os.path.join(person_test_dir, f"id_{name}.txt"))
            if card_number:
                if dry_run:
                    counts["id_cards_created"] += 1
                else:
                    if db.query(IDCard).filter_by(card_number=card_number).first():
                        counts["id_cards_skipped"] += 1
                    else:
                        db.add(IDCard(person_id=person.id, card_number=card_number, status=VehicleStatus.ACTIVE))
                        counts["id_cards_created"] += 1

        if not dry_run:
            db.commit()
    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()

    return {"ok": True, "dry_run": dry_run, "counts": counts, "log": log}


def clear_demo() -> dict:
    """Deletes all rows from the demo-populated tables (FK-safe order).
    Does NOT drop tables - safe to re-seed (with demo or real data) after."""
    db = SessionLocal()
    try:
        counts = {}
        for model in [AttendanceEvent, RecognitionEvent, FaceEmbedding, Vehicle, IDCard, Person]:
            counts[model.__tablename__] = db.query(model).delete()
        db.commit()
        return {"ok": True, "deleted": counts}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
