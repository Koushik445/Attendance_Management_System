"""
Small shared bootstrap so the standalone scripts in /scripts and /ml can
import the FastAPI app's config/db/models without duplicating code.

It adds backend/ to sys.path (so `import app.xxx` works) and loads the
project's .env file regardless of which directory the script is run from.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Make relative dataset paths in .env resolve from the project root
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
