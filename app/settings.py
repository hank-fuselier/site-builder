"""All configuration comes from environment variables so the app can move hosts unchanged."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "sitebuilder.db"

# Public base URL that customer preview links are built from, e.g. https://sites.example.com
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
AI_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY"))

# Your business details shown in the small "built by" footer on previews (optional)
BUILDER_NAME = os.environ.get("BUILDER_NAME", "")

for d in (DATA_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)
