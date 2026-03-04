import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# DB will be inside instance/attendance.db
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

DB_PATH = INSTANCE_DIR / "attendance.db"

SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key")