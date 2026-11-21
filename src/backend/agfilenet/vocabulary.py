"""Words in the collection that mean nearly the same as a word in the query.

A file about "smuggling" should come up for "trafficking" even though the
word is not in it. Every word of the collection is embedded once with the
local model (and kept in a file beside the database); a query word is then
fanned out to its nearest neighbours among them.

Words are compared as they are written, not as index terms: "trafficking"
is indexed under "traffic", but it is not about cars.
"""
import functools
import re
import threading

import numpy as np

from . import config, embed
from .textutil import stem

MIN_SIMILARITY = 0.78   # below this single words are only loosely associated ("zebra" ~ "purple")
PER_WORD = 3

_lock = threading.Lock()        # guards the tables below
_learning = threading.Lock()    # one embedding run at a time
_vectors = {}                   # word -> unit vector
_loaded = set()                 # cache files already read
_matrix = None                  # (words, matrix), rebuilt after learning


def eligible(word):
    """Plain words only; numbers, references and fragments have no meaning to compare."""
    return len(word) >= 4 and word.isascii() and word.isalpha()


def _cache_file():
    return config.VAR_DIR / f"vocabulary-{re.sub(r'[^A-Za-z0-9]+', '-', config.EMBED_MODEL)}.npz"


def _load():
    path = _cache_file()
    with _lock:
        if path in _loaded:
            return
        _loaded.add(path)
    try:
        with np.load(path, allow_pickle=False) as saved:
            found = dict(zip(saved["words"].tolist(), saved["vectors"]))
    except (OSError, ValueError, KeyError):
        return
    with _lock:
        _vectors.update(found)


def learn(words):
    """Embed the words not yet known. Slow the first time (about a minute per 4,000 words)."""
    global _matrix
    _load()
    with _learning:
        missing = sorted({w for w in words if eligible(w)} - _vectors.keys())
        if not missing:
            return 0
        vectors = embed.embed_passages(missing)
        with _lock:
            _vectors.update(zip(missing, vectors))
            _matrix = None
            known = sorted(_vectors)
            table = np.array([_vectors[w] for w in known], dtype=np.float32)
        path = _cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            np.savez(f, words=np.array(known), vectors=table)
        return len(missing)


def learn_in_background(words):
    """Start learning without holding up a search; until it finishes fewer related words are found."""
    words = [w for w in words if eligible(w)]
    _load()
    if any(w not in _vectors for w in words):
        threading.Thread(target=learn, args=(words,), daemon=True).start()


@functools.lru_cache(maxsize=2048)
def _vector(word):
    known = _vectors.get(word)
    return known if known is not None else embed.embed_passages([word])[0]


def neighbours(word, written):
    """[(index term, similarity)] for the collection words closest in meaning to `word`, best first.

    `written` maps each index term to the form it is usually written in. The
    word's own term is never returned.
    """
    global _matrix
    word = word.lower()
    if not eligible(word):
        return []
    term_of = _terms_of(written)
    with _lock:
        if _matrix is None:
            known = sorted(_vectors)
            _matrix = (known, np.array([_vectors[w] for w in known], dtype=np.float32) if known else None)
        known, table = _matrix
    if not known:
        return []
    similarity = table @ _vector(word)
    out, own = [], stem(word)
    for i in np.argsort(-similarity):
        if similarity[i] < MIN_SIMILARITY or len(out) == PER_WORD:
            break
        term = term_of.get(known[i])
        if term and term != own and all(term != t for t, _s in out):
            out.append((term, float(similarity[i])))
    return out


_term_tables = {}


def _terms_of(written):
    """{written form: index term}, kept per vocabulary so it is not rebuilt for every query word."""
    table = _term_tables.get(id(written))
    if table is None or table[0] is not written:
        _term_tables.clear()
        table = _term_tables[id(written)] = (written, {form: term for term, form in written.items()})
    return table[1]
