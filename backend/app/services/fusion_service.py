"""
Thin adapter between the backend (which knows about settings/thresholds)
and fusion/decision_engine.py (which deliberately knows nothing about the
app, the database, or ML models - see that file's docstring).
"""
import os
import sys

# fusion/ lives at the project root, one level above backend/ - add it to
# sys.path so `from fusion.decision_engine import decide` resolves
# regardless of the working directory the server was started from.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fusion.decision_engine import decide  # noqa: E402

from app.core.config import settings  # noqa: E402

THRESHOLDS = {
    "face_high": settings.FACE_SIM_HIGH,
    "face_low": settings.FACE_SIM_LOW,
    "plate_high": settings.PLATE_CONF_HIGH,
    "plate_low": settings.PLATE_CONF_LOW,
}


def run_fusion(evidence: dict) -> dict:
    return decide(evidence, thresholds=THRESHOLDS)
