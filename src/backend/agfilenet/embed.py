"""Local sentence embeddings (fastembed / onnxruntime)."""
import threading

import numpy as np

from . import config

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(config.EMBED_MODEL)
    return _model


def embed_passages(texts):
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    vectors = np.array(list(_get_model().passage_embed(texts)), dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def embed_query(text):
    vector = np.array(next(iter(_get_model().query_embed(text))), dtype=np.float32)
    return vector / np.linalg.norm(vector)
