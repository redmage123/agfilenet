"""Second reading of the best results by a cross-encoder.

The embedding model compares a query and a passage as two separate vectors.
A cross-encoder reads the two together, word against word, which is slower
but a better judge of whether the passage really answers the query. It is
therefore run only on the passages the first stage already put on top.
"""
import threading

import numpy as np

from . import config, models

BATCH = 8               # passages read at a time; bounds the memory a reading takes
MAX_TOKENS = 512        # the model's limit; a longer passage loses its end

_lock = threading.Lock()
_loaded = None          # (session, tokenizer), or False when the model's files are absent


def _load():
    global _loaded
    with _lock:
        if _loaded is None:
            files = [models.path(config.RERANK_MODEL, f) for f in config.RERANK_FILES]
            if not all(files):
                _loaded = False
            else:
                import onnxruntime
                from tokenizers import Tokenizer
                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = config.LLM_THREADS
                options.enable_cpu_mem_arena = False    # give memory back after each reading
                session = onnxruntime.InferenceSession(files[0], options, providers=["CPUExecutionProvider"])
                tokenizer = Tokenizer.from_file(files[1])
                tokenizer.enable_truncation(MAX_TOKENS, strategy="only_second")
                tokenizer.enable_padding()
                _loaded = (session, tokenizer)
        return _loaded


def available():
    return _loaded is not False and models.present(config.RERANK_MODEL)


def scores(query, passages):
    """How well each passage answers the query, 0..1; None without the model."""
    loaded = available() and _load()
    if not loaded or not passages:
        return None
    session, tokenizer = loaded
    wanted = {i.name for i in session.get_inputs()}
    logits = []
    with _lock:
        for start in range(0, len(passages), BATCH):
            batch = tokenizer.encode_batch([(query, p) for p in passages[start:start + BATCH]])
            feed = {"input_ids": np.array([e.ids for e in batch], dtype=np.int64),
                    "attention_mask": np.array([e.attention_mask for e in batch], dtype=np.int64),
                    "token_type_ids": np.array([e.type_ids for e in batch], dtype=np.int64)}
            out = session.run(None, {k: v for k, v in feed.items() if k in wanted})[0]
            logits.extend(out.reshape(len(batch), -1)[:, 0].tolist())
    return 1.0 / (1.0 + np.exp(-np.array(logits, dtype=np.float64)))
