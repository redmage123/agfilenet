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

# Every model runs on this machine. They are fetched once into MODEL_DIR
# (`python -m agfilenet models`); a feature whose model is absent is switched off.
MODEL_DIR = Path(os.environ.get("AGFILENET_MODELS") or os.environ.get("FASTEMBED_CACHE_PATH")
                 or REPO_ROOT / "var" / "models").resolve()
RERANK_MODEL = os.environ.get("AGFILENET_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
RERANK_FILES = ("onnx/model.onnx", "tokenizer.json")
NER_MODEL = os.environ.get("AGFILENET_NER_MODEL", "Xenova/bert-base-NER")
NER_FILES = ("onnx/model_quantized.onnx", "tokenizer.json", "config.json")
LLM_REPO = os.environ.get("AGFILENET_LLM_REPO", "Qwen/Qwen2.5-1.5B-Instruct-GGUF")
LLM_FILE = os.environ.get("AGFILENET_LLM_FILE", "qwen2.5-1.5b-instruct-q4_k_m.gguf")
LLM_THREADS = int(os.environ.get("AGFILENET_LLM_THREADS", "4"))
LLM_IDLE_SECONDS = int(os.environ.get("AGFILENET_LLM_IDLE", "300"))   # the model leaves memory after this
