"""
Centralised configuration.

Every tunable value (DB URL, thresholds, model paths) is read from environment
variables / .env so that nothing is hard-coded in application logic.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root (two levels above backend/app/core/),
# regardless of the current working directory the process was started from.
# This lets `.env` and dataset paths resolve correctly whether you run
# `uvicorn` from backend/ or a script from the project root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")


class Settings(BaseSettings):
    # --- App ---
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret"
    API_PREFIX: str = "/api"
    CORS_ORIGINS: str = "http://localhost:5500"

    # --- Database ---
    DATABASE_URL: str

    # --- Dataset paths ---
    FACE_DATASET_TRAIN_DIR: str = "datasets/face_dataset/Image_Train"
    FACE_DATASET_TEST_DIR: str = "datasets/face_dataset/Image_Test"
    PLATE_DATASET_TRAIN_DIR: str = "datasets/number_plate_dataset/train"
    PLATE_DATASET_TEST_DIR: str = "datasets/number_plate_dataset/test"

    # --- Models ---
    FACE_MODEL_NAME: str = "buffalo_l"
    YOLO_MODEL_PATH: str = "models/yolov8n.pt"
    PLATE_DETECTOR_MODEL_PATH: str = "models/plate_detector.pt"

    # --- Fusion thresholds ---
    FACE_SIM_HIGH: float = 0.55
    FACE_SIM_LOW: float = 0.35
    PLATE_CONF_HIGH: float = 0.85
    PLATE_CONF_LOW: float = 0.55
    ID_MATCH_CONFIDENCE: float = 0.99
    FUSION_VERIFY_THRESHOLD: float = 0.70
    FUSION_REVIEW_THRESHOLD: float = 0.40

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def _resolve(self, relative_path: str) -> str:
        """Dataset paths in .env are written relative to the project root
        (e.g. `datasets/face_dataset/Image_Train`). Resolve them to an
        absolute path so they work no matter where the process was started."""
        if os.path.isabs(relative_path):
            return relative_path
        return os.path.join(PROJECT_ROOT, relative_path)

    @property
    def face_train_path(self) -> str:
        return self._resolve(self.FACE_DATASET_TRAIN_DIR)

    @property
    def face_test_path(self) -> str:
        return self._resolve(self.FACE_DATASET_TEST_DIR)

    @property
    def plate_train_path(self) -> str:
        return self._resolve(self.PLATE_DATASET_TRAIN_DIR)

    @property
    def plate_test_path(self) -> str:
        return self._resolve(self.PLATE_DATASET_TEST_DIR)


@lru_cache
def get_settings() -> Settings:
    """Settings are loaded once and cached (singleton)."""
    return Settings()


settings = get_settings()
