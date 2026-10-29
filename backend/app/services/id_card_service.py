"""
ID-card verification module.

For this prototype, ID-card OCR is NOT implemented - an external OCR
scanner is assumed to already provide plain text (e.g. "DEMO001" or the
demo dataset's "id_ABHAY" style ground-truth files). This module only does
text normalization + database lookup.

Interface contract (kept stable so a real OCR module can replace the text
source later without touching the fusion engine or the API route):

    verify_id_text(db, raw_text: str) -> IDCardMatch
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import IDCard, Person


def normalize_id_text(raw_text: str) -> str:
    """Uppercase, keep only letters/digits. This makes 'DEMO001',
    'demo-001', and the dataset's 'id_ABHAY' file contents all compare
    consistently regardless of separators/case."""
    return re.sub(r"[^A-Z0-9]", "", raw_text.upper())


@dataclass
class IDCardMatch:
    person_id: int | None
    person_name: str | None
    employee_id: str | None
    matched_card_number: str | None
    confidence: float
    status: str  # MATCHED / UNKNOWN


def verify_id_text(db: Session, raw_text: str) -> IDCardMatch:
    normalized = normalize_id_text(raw_text)
    if not normalized:
        return IDCardMatch(None, None, None, None, 0.0, "UNKNOWN")

    # 1. Exact match against registered id_cards.card_number (normalized).
    for card in db.query(IDCard).all():
        if normalize_id_text(card.card_number) == normalized:
            person = db.query(Person).filter_by(id=card.person_id).first()
            return IDCardMatch(
                person_id=card.person_id,
                person_name=person.name if person else None,
                employee_id=person.employee_id if person else None,
                matched_card_number=card.card_number,
                confidence=settings.ID_MATCH_CONFIDENCE,
                status="MATCHED",
            )

    # 2. Fallback: the OCR text might directly be the employee_id.
    person = db.query(Person).filter(Person.employee_id.ilike(normalized)).first()
    if person:
        return IDCardMatch(
            person_id=person.id,
            person_name=person.name,
            employee_id=person.employee_id,
            matched_card_number=None,
            confidence=settings.ID_MATCH_CONFIDENCE,
            status="MATCHED",
        )

    return IDCardMatch(None, None, None, None, 0.0, "UNKNOWN")
