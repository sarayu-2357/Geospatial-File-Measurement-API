"""Central settings so numbers aren't scattered through the code."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE_URL = f"sqlite:///{BASE_DIR / 'geo.db'}"

ALLOWED_EXTENSIONS = {".kml", ".zip"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024          # 50 MB upload
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024   # zip-bomb guard
MAX_ZIP_MEMBERS = 100

# If projected and geodesic results differ by more than this %, flag "low".
ACCURACY_THRESHOLD_PCT = 0.3