"""Small text helpers shared by metadata extraction and search."""
import functools
import re

import lemminflect
import wordninja

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below
between both but by can did do does doing down during each few for from further had has have
having he her here hers him his how i if in into is it its just me more most my no nor not now
of off on once only or other our out over own same she should so some such than that the their
them then there these they this those through to too under until up very was we were what when
where which while who whom why will with you your said shall may would upon herein hereby
thereof therein
""".split())

_WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
_LONG_ALPHA = re.compile(r"[A-Za-z]{13,}")


def squash(text):
    """Lowercase and drop everything but letters and digits.

    OCR often loses the spaces in headings ("WRITOFSUMMONS"), so phrase rules
    are matched against this form.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def unglue(text):
    """Split long run-together alphabetic tokens that OCR produced without spaces."""
    def fix(m):
        word = m.group(0)
        parts = wordninja.split(word)
        if len(parts) < 2 or any(len(p) == 1 and p.lower() not in ("a", "i") for p in parts):
            return word
        return " ".join(parts)
    return _LONG_ALPHA.sub(fix, text)


def is_word(token):
    """Whether the dictionary knows this (lowercase) word in some form."""
    return token in STOPWORDS or bool(lemminflect.getAllLemmas(token))


@functools.lru_cache(maxsize=200_000)
def stem(token):
    """The dictionary form of a word, so 'smuggled', 'smuggles' and 'smuggling' are one term.

    Words the dictionary lacks (names, references, OCR misreadings) only lose a
    plural or possessive ending.
    """
    t = token.lower().replace("’", "'")
    if t.endswith("'s"):
        t = t[:-2]
    if t.isascii() and t.isalpha():
        forms = lemminflect.getAllLemmas(t)
        lemmas = [lemma for pos in ("VERB", "NOUN", "ADJ") for lemma in forms.get(pos, ()) if lemma.isalpha()]
        if lemmas:
            return min(lemmas, key=len).lower()   # 'building' -> 'build', 'damages' -> 'damage'
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith(("ches", "shes", "xes", "zes", "sses")):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def words(text, keep_stop=False):
    """[(term, the word as written, lowercase)] for the words of a text that are worth indexing."""
    out = []
    for m in _WORD.finditer(text):
        t = stem(m.group(0))
        if len(t) < 2 and not t.isdigit():
            continue
        if not keep_stop and (t in STOPWORDS or m.group(0).lower() in STOPWORDS):
            continue
        out.append((t, m.group(0).lower()))
    return out


def tokens(text, keep_stop=False):
    return [t for t, _written in words(text, keep_stop)]


def written_forms(texts):
    """{term: the form it is most often written in} over some texts ('smuggle' -> 'smuggling')."""
    forms = {}
    for text in texts:
        for term, written in words(text):
            counts = forms.setdefault(term, {})
            counts[written] = counts.get(written, 0) + 1
    return {term: max(sorted(counts), key=counts.get) for term, counts in forms.items()}


def norm_name(text):
    """Normalise a name or reference for equality matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/& ]", " ", text.lower())).strip()


def chunk_text(text, size=160, overlap=40):
    """Split page text into overlapping word windows for embedding."""
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]
    chunks, step = [], size - overlap
    for start in range(0, len(words), step):
        if chunks and start + overlap >= len(words):
            break  # what is left is already inside the previous window
        chunks.append(" ".join(words[start:start + size]))
    return chunks
