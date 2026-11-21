"""Tidying the names the model finds, and treating different spellings of one name as one entity.

"A. Thompson", "Angela Thompson" and OCR's "Angela Thonpson" are the same
person when they turn up in the same matter. Merging is deliberately
cautious: two names are only joined if a file or a matter contains both, and
an initial is only expanded when exactly one full name fits it.
"""
import re

from .spelling import _one_edit
from .textutil import norm_name

_TITLE = re.compile(r"^(?:(?:Mr|Mrs|Ms|Miss|Dr|Hon|Justice|Sir|Dame|Madam|Sgt|Inspector|Atty|The)\b\.?\s+)+", re.I)
_NOT_NAMES = {"plaintiff", "defendant", "respondent", "applicant", "appellant", "claimant", "dear", "sir", "madam",
              "re", "between", "and", "the", "of", "date", "dated", "summons", "writ", "page", "tel", "fax", "your",
              "our", "yours", "attorney", "general", "counsel", "secretary", "minister", "director", "reference",
              "street", "road", "box", "no", "esq", "vendor", "purchaser", "mortgagor", "mortgagee"}
_ORG_EDGE = {"of", "the", "and", "&", "for", "in", "at", "to"}


def _tidy(value):
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-–'’\"()")
    return value.title() if value.isupper() else value


def clean(kind, value):
    """The name as it should be stored, or None if it is not worth keeping."""
    value = _tidy(_TITLE.sub("", _tidy(value)))
    words = value.split()
    if not words or any(c.isdigit() for c in value) or not all(w[0].isalpha() for w in words):
        return None
    lower = [w.lower().strip(".") for w in words]
    if kind == "person":
        ok = 2 <= len(words) <= 4 and all(w[0].isupper() for w in words) and not set(lower) & _NOT_NAMES \
            and len(lower[-1]) > 2 and sum(len(w) > 1 for w in lower) >= 1 and len(value) <= 40
    elif kind == "org":
        half = len(words) // 2
        ok = len(words) >= 2 and 5 < len(value) < 70 and lower[0] not in _ORG_EDGE and lower[-1] not in _ORG_EDGE \
            and not set(lower) <= _NOT_NAMES and not (len(words) % 2 == 0 and lower[:half] == lower[half:])
        value = value[0].upper() + value[1:]
    else:
        ok = len(value) >= 4 and len(words) <= 4 and words[0][0].isupper() and not set(lower) & _NOT_NAMES
    return value if ok else None


def _fits(short, full):
    """Whether one name could be a shorter writing of the other: same surname, given names agree or are initials."""
    if short[-1] != full[-1] or short == full:
        return False
    a, b = short[:-1], full[:-1]
    if len(a) > len(b):
        a, b = b, a
    if not a:
        return False

    def same(x, y):
        return x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
    # the first given name must agree; any others of the shorter must appear in order
    if not same(a[0], b[0]):
        return False
    rest = iter(b[1:])
    return all(any(same(x, y) for y in rest) for x in a[1:])


def cluster(names):
    """Decide which names are the same entity.

    names: {(kind, norm): {"count": int, "where": set of files and matters it occurs in}}
    Returns {(kind, norm): (kind, norm of the name it is stored under)} for every name given.
    """
    parent = {key: key for key in names}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def together(a, b):
        return bool(names[a]["where"] & names[b]["where"])

    def _lopsided(a, b):
        # two real people can differ by a letter (Joan, John); a misreading is rare beside the name it garbles
        low, high = sorted((names[a]["count"], names[b]["count"]))
        return low <= 2 and high >= 3 * low

    by_kind = {}
    for key in names:
        by_kind.setdefault(key[0], []).append(key)
    for kind, keys in by_kind.items():
        keys.sort()
        tokens = {key: key[1].split() for key in keys}
        if kind == "person":
            by_surname = {}
            for key in keys:
                by_surname.setdefault(tokens[key][-1], []).append(key)
            for group in by_surname.values():
                for key in group:
                    fits = [o for o in group if o != key and together(key, o) and _fits(tokens[key], tokens[o])
                            and sum(len(t) > 1 for t in tokens[o]) >= sum(len(t) > 1 for t in tokens[key])]
                    # an initial that fits two different people in the matter is left alone
                    if len({root(o) for o in fits}) == 1:
                        parent[root(key)] = root(fits[0])
        # one-letter differences in a long name: a misreading
        by_shape = {}
        for key in keys:
            by_shape.setdefault((len(tokens[key]), len(key[1]) // 2), []).append(key)
        for key in keys:
            norm = key[1]
            if len(norm) < 8:
                continue
            for near in ((len(tokens[key]), len(norm) // 2 + d) for d in (-1, 0, 1)):
                for other in by_shape.get(near, ()):
                    if other > key and together(key, other) and _one_edit(norm, other[1]) and _lopsided(key, other):
                        parent[root(key)] = root(other)
        if kind == "org":
            plain = {}
            for key in keys:
                plain.setdefault(" ".join(w for w in key[1].split() if w not in ("the", "and", "&")), []).append(key)
            for group in plain.values():
                for other in group[1:]:
                    parent[root(other)] = root(group[0])

    groups = {}
    for key in names:
        groups.setdefault(root(key), []).append(key)
    out = {}
    for members in groups.values():
        # stored under the fullest spelling, then the commonest
        best = max(members, key=lambda k: (sum(len(t) > 1 for t in k[1].split()), names[k]["count"], len(k[1]), k))
        for key in members:
            out[key] = best
    return out


def key(value):
    return norm_name(value)
