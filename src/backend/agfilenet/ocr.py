"""Local OCR for scanned pages (RapidOCR on onnxruntime; nothing leaves the machine)."""
import threading

import numpy as np

from .textutil import unglue

_engine = None
_lock = threading.Lock()

# Below this quality the page is re-read at other rotations.
ROTATE_BELOW = 0.84


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _lines(result):
    """Assemble detected boxes into reading-order lines."""
    boxes = []
    for box, text, conf in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), text, float(conf)))
    if not boxes:
        return []
    height = float(np.median([b[2] for b in boxes])) or 1.0
    boxes.sort(key=lambda b: b[0])
    lines, current = [], [boxes[0]]
    for b in boxes[1:]:
        if abs(b[0] - current[-1][0]) < 0.6 * height:
            current.append(b)
        else:
            lines.append(current)
            current = [b]
    lines.append(current)
    return [" ".join(b[3] for b in sorted(line, key=lambda b: b[1])) for line in lines]


def _read(image):
    result, _ = _get_engine()(image)
    result = result or []
    chars = sum(len(r[1]) for r in result)
    conf = sum(float(r[2]) * len(r[1]) for r in result) / chars if chars else 0.0
    return result, conf, chars


def ocr_image(image):
    """OCR a grayscale/RGB numpy image.

    Returns (text, confidence, rotation) where rotation is the clockwise
    correction in degrees that made the page upright.
    """
    with _lock:
        best = (*_read(image), 0)
        if best[2] >= 20 and best[1] < ROTATE_BELOW:
            for k, degrees in ((1, 270), (3, 90), (2, 180)):
                cand = (*_read(np.ascontiguousarray(np.rot90(image, k))), degrees)
                # Prefer clearly more confident reads with comparable amounts of text.
                if cand[1] * min(cand[2], 4000) ** 0.5 > 1.15 * best[1] * min(best[2], 4000) ** 0.5:
                    best = cand
    result, conf, _chars, rotation = best
    text = unglue("\n".join(_lines(result)))
    return text, round(conf, 4), rotation
