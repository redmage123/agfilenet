"""Turn source files (PDF, TIFF, images) into per-page text and viewable page images."""
import io

import numpy as np
import pymupdf
from PIL import Image, ImageSequence

from . import config, ocr

MIN_TEXT_LAYER = 40  # characters; below this a PDF page is treated as image-only

CONTENT_TYPES = {
    ".pdf": "application/pdf", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
}


def _pdf_page_image(page, dpi):
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _image_frames(path):
    with Image.open(path) as im:
        for frame in ImageSequence.Iterator(im):
            yield frame.convert("L")


def extract_pages(path, progress=None):
    """Yield dicts {page_no, text, source, ocr_conf, rotation} for every page of a file."""
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                if len(text) >= MIN_TEXT_LAYER:
                    yield {"page_no": i + 1, "text": text, "source": "text",
                           "ocr_conf": None, "rotation": 0}
                else:
                    text, conf, rot = ocr.ocr_image(_pdf_page_image(page, config.OCR_DPI))
                    yield {"page_no": i + 1, "text": text, "source": "ocr",
                           "ocr_conf": conf, "rotation": rot}
                if progress:
                    progress()
    else:
        for i, frame in enumerate(_image_frames(path)):
            text, conf, rot = ocr.ocr_image(np.asarray(frame))
            yield {"page_no": i + 1, "text": text, "source": "ocr",
                   "ocr_conf": conf, "rotation": rot}
            if progress:
                progress()


def count_pages(path):
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            return doc.page_count
    with Image.open(path) as im:
        return getattr(im, "n_frames", 1)


def render_page_png(path, page_no, rotation=0):
    """PNG bytes of one page, turned upright using the rotation found at ingest."""
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            image = Image.fromarray(_pdf_page_image(doc[page_no - 1], config.VIEW_DPI))
    else:
        frames = list(_image_frames(path))
        image = frames[page_no - 1]
        image.thumbnail((1400, 1800))
    if rotation:
        image = image.rotate(-rotation, expand=True)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
