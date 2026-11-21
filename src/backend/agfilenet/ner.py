"""Names of people, organisations and places, found by a local token-classification model.

The pattern rules in metadata.py only see a person behind a title ("Mr.
Peter Rolle") or in a court heading. The model reads the sentence, so it
also finds the signatory of a letter or a witness named in passing. It was
trained on ordinary mixed-case text, so headings in capitals are lowered to
title case before it sees them.
"""
import json
import re
import threading

import numpy as np

from . import config, models

MIN_CONFIDENCE = 0.80
WINDOW = 380            # word pieces per run of the model (its limit is 512)
KINDS = {"PER": "person", "ORG": "org", "LOC": "place"}

_lock = threading.Lock()
_loaded = None          # (session, tokenizer, labels) or False when the model is absent


def _load():
    global _loaded
    with _lock:
        if _loaded is None:
            files = [models.path(config.NER_MODEL, f) for f in config.NER_FILES]
            if not all(files):
                _loaded = False
            else:
                import onnxruntime
                from tokenizers import Tokenizer
                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = config.LLM_THREADS
                options.enable_cpu_mem_arena = False
                session = onnxruntime.InferenceSession(files[0], options, providers=["CPUExecutionProvider"])
                tokenizer = Tokenizer.from_file(files[1])
                tokenizer.no_truncation()
                tokenizer.no_padding()
                with open(files[2]) as f:
                    labels = {int(k): v for k, v in json.load(f)["id2label"].items()}
                _loaded = (session, tokenizer, labels)
        return _loaded


def unload():
    """Let go of the model; it is only needed while files are being read."""
    global _loaded
    with _lock:
        if _loaded:
            _loaded = None


def available():
    return _loaded is not False and models.present(config.NER_MODEL)


def _recase(text):
    """Title-case the words of lines written in capitals; lengths are kept so positions still match."""
    def fix(line):
        letters = [c for c in line if c.isalpha()]
        if len(letters) > 3 and sum(c.isupper() for c in letters) > 0.7 * len(letters):
            return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), line)
        return line
    return "\n".join(fix(line) for line in text.split("\n"))


def _softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def find(text):
    """[(kind, text as written, confidence)] for the names in a page of text; [] without the model."""
    loaded = available() and _load()
    if not loaded or not text.strip():
        return []
    session, tokenizer, labels = loaded
    recased = _recase(text)
    encoding = tokenizer.encode(recased, add_special_tokens=False)
    ids, offsets = encoding.ids, encoding.offsets
    cls, sep = tokenizer.token_to_id("[CLS]"), tokenizer.token_to_id("[SEP]")
    names = {i.name for i in session.get_inputs()}
    tags = []                                       # (label, probability) per word piece
    for start in range(0, len(ids), WINDOW):
        piece = [cls] + ids[start:start + WINDOW] + [sep]
        feed = {"input_ids": np.array([piece], dtype=np.int64),
                "attention_mask": np.ones((1, len(piece)), dtype=np.int64)}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.zeros((1, len(piece)), dtype=np.int64)
        probabilities = _softmax(session.run(None, feed)[0][0][1:-1])
        best = probabilities.argmax(axis=-1)
        tags += [(labels[int(b)], float(p[b])) for b, p in zip(best, probabilities)]

    found, current = [], None                       # current = [kind, start, end, [probabilities]]
    for (label, probability), (a, b) in zip(tags, offsets):
        kind = label[2:] if label != "O" else None
        continues = current and kind == current[0] and (label.startswith("I-") or a == current[2]) \
            and "\n" not in text[current[2]:a]
        if continues:
            current[2] = b
            current[3].append(probability)
            continue
        if current:
            found.append(current)
        current = [kind, a, b, [probability]] if kind in KINDS else None
    if current:
        found.append(current)

    out = []
    for kind, a, b, probabilities in found:
        # finish the word the last piece belongs to
        while b < len(text) and (text[b].isalnum() or text[b] in "'’-") and not text[b - 1].isspace():
            b += 1
        confidence = float(np.mean(probabilities))
        if confidence >= MIN_CONFIDENCE:
            out.append((KINDS[kind], text[a:b], round(confidence, 3)))
    return out
