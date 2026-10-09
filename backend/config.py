from pathlib import Path
import os
import secrets

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

ENVIRONMENT = os.getenv("SHUHUL_ENV", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

PROCESSED_ROOT = Path(os.getenv("SHUHUL_PROCESSED_ROOT", PROJECT_ROOT / "processed"))
OUTPUT_ROOT = Path(os.getenv("SHUHUL_OUTPUT_ROOT", PROJECT_ROOT / "outputs"))
DATABASE_PATH = Path(os.getenv("SHUHUL_DATABASE", BACKEND_DIR / "shuhul.db"))

# A full database URL wins over the SQLite file, e.g.
# postgresql+psycopg2://user:password@host:5432/shuhul
DATABASE_URL = os.getenv("SHUHUL_DATABASE_URL") or f"sqlite:///{DATABASE_PATH.as_posix()}"

# Comma-separated list of origins allowed to call the API with cookies.
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
    if origin.strip()
]
DEFAULT_DISTRICT = os.getenv("SHUHUL_DEFAULT_DISTRICT", "sxr")

# In development the API runs queued analyses itself. In production a
# separate worker process does (python -m backend.worker).
INLINE_WORKER = os.getenv("SHUHUL_INLINE_WORKER", "0" if IS_PRODUCTION else "1") == "1"

MAX_ACTIVE_PROJECTS_PER_USER = int(os.getenv("SHUHUL_MAX_ACTIVE_PROJECTS", "2"))

_PLACEHOLDER_SECRETS = {
    "",
    "dev-only-change-this",
    "replace-this-with-a-long-random-secret",
}


def _load_secret_key():
    """
    Session signing key. Production refuses to start without a real one.
    Development keeps a generated key in a local file so sessions survive
    restarts without anything being committed.
    """
    value = os.getenv("SHUHUL_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or ""

    if value not in _PLACEHOLDER_SECRETS and len(value) >= 32:
        return value

    if IS_PRODUCTION:
        raise RuntimeError(
            "SHUHUL_SECRET_KEY must be set to a random value of at least "
            "32 characters when SHUHUL_ENV=production."
        )

    key_file = BACKEND_DIR / ".dev_secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


SECRET_KEY = _load_secret_key()
