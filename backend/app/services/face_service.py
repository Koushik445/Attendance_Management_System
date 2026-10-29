"""
Face recognition service.

- Uses a PRETRAINED InsightFace model (buffalo_l = RetinaFace detector +
  ArcFace embedder). Nothing is trained here.
- The model is loaded ONCE (module-level singleton) and reused across every
  request/script - loading InsightFace per-call would be far too slow.
- `recognize_embedding()` does the nearest-neighbour search directly in
  Postgres using pgvector's cosine_distance operator, so the "database is
  the source of truth" principle holds: this function returns a person_id,
  never a name.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import FaceEmbedding, Person

_model_lock = threading.Lock()
_face_app = None  # lazy singleton


def get_face_app():
    """Lazily load and cache the InsightFace FaceAnalysis app.

    Import is done inside the function so that this module can still be
    imported (e.g. by FastAPI at startup for route registration) even
    before `pip install insightface onnxruntime` has been run for
    Milestone/Phase 3 testing.
    """
    global _face_app
    if _face_app is None:
        with _model_lock:
            if _face_app is None:
                from insightface.app import FaceAnalysis

                app = FaceAnalysis(name=settings.FACE_MODEL_NAME)
                # ctx_id=-1 forces CPU. Use ctx_id=0 if you have a CUDA GPU set up.
                app.prepare(ctx_id=-1, det_size=(640, 640))
                _face_app = app
    return _face_app


@dataclass
class FaceExtractionResult:
    embedding: np.ndarray | None
    num_faces_detected: int
    det_score: float | None  # detector confidence for the chosen face


def extract_embedding(image_bgr: np.ndarray) -> FaceExtractionResult:
    """Detect the largest/most confident face in the image and return its
    512-d ArcFace embedding (L2-normalised). Returns embedding=None if no
    face was detected."""
    app = get_face_app()
    faces = app.get(image_bgr)

    if not faces:
        return FaceExtractionResult(embedding=None, num_faces_detected=0, det_score=None)

    # If multiple faces are detected, pick the highest-confidence one.
    best = max(faces, key=lambda f: f.det_score)
    embedding = best.normed_embedding.astype(np.float32)  # already L2-normalised by insightface
    return FaceExtractionResult(
        embedding=embedding,
        num_faces_detected=len(faces),
        det_score=float(best.det_score),
    )


@dataclass
class FaceMatch:
    person_id: int | None
    person_name: str | None
    similarity: float  # cosine similarity, 1.0 = identical, higher is better
    confidence_label: str  # HIGH / LOW (see thresholds)


def _confidence_label(similarity: float) -> str:
    if similarity >= settings.FACE_SIM_HIGH:
        return "HIGH"
    if similarity >= settings.FACE_SIM_LOW:
        return "MEDIUM"
    return "LOW"


def recognize_embedding(db: Session, embedding: np.ndarray) -> FaceMatch:
    """Nearest-neighbour search over all stored face_embeddings using
    pgvector cosine distance. Returns the best-matching person_id + a
    calibrated confidence label - never a hard-coded name."""
    query_vec = embedding.tolist()

    row = (
        db.query(
            FaceEmbedding.person_id,
            FaceEmbedding.embedding.cosine_distance(query_vec).label("distance"),
        )
        .order_by("distance")
        .first()
    )

    if row is None:
        return FaceMatch(person_id=None, person_name=None, similarity=0.0, confidence_label="LOW")

    person_id, distance = row
    similarity = 1.0 - float(distance)  # cosine_distance = 1 - cosine_similarity
    person = db.query(Person).filter_by(id=person_id).first()

    return FaceMatch(
        person_id=person_id,
        person_name=person.name if person else None,
        similarity=similarity,
        confidence_label=_confidence_label(similarity),
    )
