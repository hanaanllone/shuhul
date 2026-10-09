from pathlib import Path
import os

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

PROCESSED_ROOT = Path(os.getenv("SHUHUL_PROCESSED_ROOT", PROJECT_ROOT / "processed"))
OUTPUT_ROOT = Path(os.getenv("SHUHUL_OUTPUT_ROOT", PROJECT_ROOT / "outputs"))
DATABASE_PATH = Path(os.getenv("SHUHUL_DATABASE", BACKEND_DIR / "shuhul.db"))

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
DEFAULT_DISTRICT = os.getenv("SHUHUL_DEFAULT_DISTRICT", "sxr")
