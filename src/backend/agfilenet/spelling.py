"""Repair of OCR misreadings against the collection's own vocabulary.

A word that the dictionary does not know and that occurs once or twice is
taken for a misreading when one edit turns it into a dictionary word the
collection uses often ("smugling" -> "smuggling"). The page text is left as
it was read; the intended word is indexed alongside it, so a search for the
right spelling finds the passage.
"""
from .textutil import is_word

MIN_LENGTH = 6      # short words are one edit away from too many others
RARE = 2            # a misreading does not keep recurring
COMMON = 5          # the intended word occurs at least this often ...
RATIO = 5           # ... and this many times as often


def _deletions(word):
    return {word[:i] + word[i + 1:] for i in range(len(word))}


def _one_edit(a, b):
    """True if b is a by one insertion, deletion, substitution or swap of neighbours."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) < len(b):
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i + 1:] or (a[i + 2:] == b[i + 2:] and a[i:i + 2] == b[i:i + 2][::-1])


def corrections(counts):
    """{misread term: intended term} for a {term: occurrences} table of the collection."""
    plain = {t: n for t, n in counts.items() if len(t) >= MIN_LENGTH - 1 and t.isascii() and t.isalpha()}
    targets = {t: n for t, n in plain.items() if n >= COMMON and is_word(t)}
    by_deletion = {}
    for t in targets:
        for key in _deletions(t) | {t}:
            by_deletion.setdefault(key, []).append(t)
    out = {}
    for word, n in plain.items():
        if n > RARE or len(word) < MIN_LENGTH or is_word(word):
            continue
        near = {t for key in _deletions(word) | {word} for t in by_deletion.get(key, ())
                if targets[t] >= RATIO * n and _one_edit(word, t)}
        if len(near) == 1:      # two possible intentions: leave it alone
            out[word] = near.pop()
    return out
