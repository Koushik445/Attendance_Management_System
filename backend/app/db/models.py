"""
SQLAlchemy ORM models.

Design principle (see project spec): the database is the source of truth for
identity. ML modules never return a name directly - they return a person_id
(or a plate_number / employee_id that is then looked up), and the fusion
engine only ever operates on person_id.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Float, JSON, Enum, func,
)
from sqlalchemy.orm import relationship

from app.db.database import Base

# pgvector gives a proper indexed vector column. If the pgvector extension
# isn't available yet in your Neon database, this import still works - you
# just need to run `CREATE EXTENSION IF NOT EXISTS vector;` once (see README).
from pgvector.sqlalchemy import Vector

FACE_EMBEDDING_DIM = 512  # ArcFace (buffalo_l) output dimension


class PersonStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VehicleStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CardStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ArrivalType(str, enum.Enum):
    WALKING = "WALKING"
    CAR = "CAR"
    BIKE = "BIKE"
    UNKNOWN = "UNKNOWN"


class DecisionStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NEEDS_ID = "NEEDS_ID"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNKNOWN = "UNKNOWN"


class AttendanceEventType(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True)
    employee_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    department = Column(String(255), nullable=True)
    status = Column(Enum(PersonStatus), default=PersonStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    face_embeddings = relationship("FaceEmbedding", back_populates="person", cascade="all, delete-orphan")
    vehicles = relationship("Vehicle", back_populates="person", cascade="all, delete-orphan")
    id_cards = relationship("IDCard", back_populates="person", cascade="all, delete-orphan")


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    embedding = Column(Vector(FACE_EMBEDDING_DIM), nullable=False)
    image_path = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    person = relationship("Person", back_populates="face_embeddings")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    plate_number = Column(String(32), unique=True, nullable=False, index=True)
    vehicle_type = Column(String(32), nullable=True)  # CAR / BIKE
    status = Column(Enum(VehicleStatus), default=VehicleStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    person = relationship("Person", back_populates="vehicles")


class IDCard(Base):
    __tablename__ = "id_cards"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    card_number = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(Enum(CardStatus), default=CardStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    person = relationship("Person", back_populates="id_cards")


class RecognitionEvent(Base):
    __tablename__ = "recognition_events"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    arrival_type = Column(Enum(ArrivalType), nullable=False)

    face_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    face_similarity = Column(Float, nullable=True)
    face_confidence = Column(Float, nullable=True)

    plate_number = Column(String(32), nullable=True)
    plate_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    plate_confidence = Column(Float, nullable=True)

    id_card_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    id_card_confidence = Column(Float, nullable=True)

    final_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    final_confidence = Column(Float, nullable=True)

    decision = Column(Enum(DecisionStatus), nullable=False)
    verification_method = Column(String(64), nullable=True)

    event_metadata = Column(JSON, nullable=True)


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False, index=True)
    event_type = Column(Enum(AttendanceEventType), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    verification_method = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    recognition_event_id = Column(Integer, ForeignKey("recognition_events.id"), nullable=True)

    person = relationship("Person")



