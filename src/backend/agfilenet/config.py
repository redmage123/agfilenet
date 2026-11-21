import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("AGFILENET_DATA", REPO_ROOT / "data")).resolve()
VAR_DIR = Path(os.environ.get("AGFILENET_VAR", REPO_ROOT / "var")).resolve()
DB_PATH = VAR_DIR / "agfilenet.fs"
PAGE_CACHE = VAR_DIR / "pages"
FRONTEND_DIST = REPO_ROOT / "src" / "frontend" / "dist"

DOC_EXTENSIONS = {".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}
OCR_DPI = 170
VIEW_DPI = 110
EMBED_MODEL = os.environ.get("AGFILENET_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
