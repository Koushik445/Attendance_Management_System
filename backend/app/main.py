from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import persons, verify, vehicles, attendance, admin, status

app = FastAPI(title="Faculty Attendance Management System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(persons.router, prefix=settings.API_PREFIX)
app.include_router(verify.router, prefix=settings.API_PREFIX)
app.include_router(vehicles.router, prefix=settings.API_PREFIX)
app.include_router(attendance.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)
app.include_router(status.router, prefix=settings.API_PREFIX)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.on_event("startup")
def preload_models():
    """Load ML models once at startup instead of on first request. Each is
    wrapped independently so a missing dependency for one modality (e.g.
    ANPR not set up yet) doesn't block the others or prevent the server
    from starting."""
    try:
        from app.services.face_service import get_face_app
        get_face_app()
        print("[startup] Face model loaded.")
    except Exception as e:
        print(f"[startup][WARN] Face model not loaded: {e}")

    try:
        from app.services.arrival_service import get_yolo_model
        get_yolo_model()
        print("[startup] YOLO arrival-detection model loaded.")
    except Exception as e:
        print(f"[startup][WARN] YOLO model not loaded: {e}")

    try:
        from app.services.anpr_service import get_ocr_reader
        get_ocr_reader()
        print("[startup] EasyOCR reader loaded.")
    except Exception as e:
        print(f"[startup][WARN] EasyOCR not loaded: {e}")
