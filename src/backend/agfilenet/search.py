"""Keyword, semantic, hybrid and IAC search over the ingested documents."""
import math
import re
import threading
from collections import Counter, defaultdict

import numpy as np

from . import embed, iac, rerank, store, vocabulary
from .textutil import norm_name, stem, tokens, words, written_forms

MODES = ("iac", "hybrid", "keyword", "semantic")

# bge-small cosine similarities sit in a narrow band. On these documents a query
# about nothing in the collection still scores up to about 0.6 against its best
# passage, and a passage on the topic 0.65-0.8. Rescale that band to 0..1.
SEM_FLOOR, SEM_SPAN = 0.58, 0.25

# Strength of document <-> property links by property kind (before idf scaling).
LINK = {"term": 1.0, "entity": 0.7, "reference": 1.5, "matter": 0.6, "type": 0.3}
REFERENCE_KINDS = ("case_no", "file_ref", "registry")   # a quoted reference is the strongest evidence there is
# Competition between documents is scaled down: several documents can be right at once.
DOC_GAMMA = 0.5
TERM_BUDGET = 2.0   # query words together drive documents like this many full-strength words
REWORDING = 0.8      # what a rewording of the whole query by the language model counts for
RELATED_FLOOR = 0.5  # a related word drives documents at (similarity - floor) / (1 - floor) of its query word
IAC_PARAMS = iac.Params()   # the textbook values
FULL_NETWORK_MAX_DOCS = 1500
CANDIDATES = 400

# Default map from settled activation to match probability (used until enough
# relevance judgements exist to fit one): p = sigmoid(A * activation + B).
DEFAULT_CALIBRATION = (12.0, -4.8)   # 50% at activation 0.4
MIN_JUDGEMENTS = 20
MIN_PROBABILITY = 0.02     # results below this are not listed

# Second reading of the best results by the cross-encoder (see rerank.py). Its
# verdict r (0..1) moves a result's log-odds by RERANK_WEIGHT * (2r - 1). When it
# finds no passage that answers the query (a description of a document rather
# than of its contents, say) it has nothing to tell the results apart by, and abstains.
RERANK_TOP = 12
RERANK_WEIGHT = 2.5
RERANK_ABSTAIN = 0.3

_lock = threading.Lock()
_index = None


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, x))))


def _idf_norm(df, n):
    """1 for a property found in one document, 0 for one found in all of them."""
    if n <= 1:
        return 1.0
    return max(0.0, math.log(n / df) / math.log(n))


class Index:
    """In-memory snapshot of the object database for fast scoring.

    Holds plain data only (no persistent objects), so it can be shared
    between request threads. Rebuilt whenever the library's revision changes.
    """

    def __init__(self, lib):
        self.revision = lib.revision
        docs = lib.ok_documents()
        self.docs = [{"id": d.id, "filename": d.filename, "path": d.path, "title": d.title,
                      "doc_type": d.doc_type, "doc_date": d.doc_date, "matter": d.matter,
                      "flags": list(d.flags), "page_count": d.page_count} for d in docs]
        self.pos = {d.id: i for i, d in enumerate(docs)}
        n = len(docs)

        chunks = [c for d in docs for c in d.chunks]
        self.chunk_doc = np.array([self.pos[c.document.id] for c in chunks], dtype=np.int64)
        self.chunk_page = [c.page_no for c in chunks]
        self.chunk_text = [c.text for c in chunks]
        self.chunk_row = {c.id: i for i, c in enumerate(chunks)}
        self.embeddings = (np.frombuffer(b"".join(c.embedding for c in chunks), dtype=np.float32)
                           .reshape(len(chunks), -1) if chunks else np.zeros((0, 1), dtype=np.float32))

        # term postings: term -> {doc index: tf}
        counts = []
        for d in docs:
            c = Counter()
            for page in d.pages:
                c.update(lib.text_index.terms(page.text or ""))
            extra = (d.title, d.subject, d.matter, d.filename, d.decl_matter_title, d.decl_reference,
                     d.decl_comments)
            c.update(tokens(" ".join(str(x) for x in extra if x)))
            counts.append(c)
        postings = defaultdict(dict)
        for i, c in enumerate(counts):
            for term, tf in c.items():
                postings[term][i] = tf
        self.term_links = {}
        for term, tfs in postings.items():
            idf = _idf_norm(len(tfs), n)
            # saturating term frequency keeps weights in 0..1; no length penalty,
            # a long file that contains the word is still a file that contains it
            self.term_links[term] = {i: idf * tf / (tf + 0.5) for i, tf in tfs.items()}
        self.term_idf = {t: _idf_norm(len(d), n) for t, d in postings.items()}
        # the form each term is usually written in, for comparing words by meaning
        self.written = {t: w for t, w in written_forms(self.chunk_text).items() if t in self.term_links}
        vocabulary.learn_in_background(self.written.values())

        # entity links, read off the Document -> Mention -> Entity references
        self.entities = {}
        for i, d in enumerate(docs):
            for m in d.mentions:
                e = self.entities.setdefault(m.entity.id, {
                    "id": m.entity.id, "kind": m.entity.kind, "value": m.entity.value,
                    "norm": m.entity.norm, "tokens": m.entity.norm.split(), "docs": {}})
                e["docs"][i] = m.count
        for e in self.entities.values():
            idf = _idf_norm(len(e["docs"]), n)
            e["links"] = {i: min(1.0, 1.2 * idf * (1 - 0.5 ** c)) for i, c in e["docs"].items()}

        # matters and document types
        self.matters, self.types = defaultdict(list), defaultdict(list)
        for i, d in enumerate(self.docs):
            if d["matter"]:
                self.matters[d["matter"]].append(i)
            if d["doc_type"]:
                self.types[d["doc_type"]].append(i)
        self.matter_refs = {m.number: m.reference for m in lib.matters.values()}
        self.calibration, self.judgements = _fit_calibration(lib)


def get_index(lib):
    global _index
    with _lock:
        if _index is None or _index.revision != lib.revision or _index.owner != id(store.database()):
            _index = Index(lib)
            _index.owner = id(store.database())
        return _index


# --- calibration from relevance judgements ----------------------------------
def _fit_calibration(lib):
    rows = [(j.activation, j.relevant) for j in lib.judgements.values() if j.activation is not None]
    n = len(rows)
    y = np.array([float(r) for _a, r in rows])
    if n < MIN_JUDGEMENTS or y.sum() < 5 or (n - y.sum()) < 5:
        return DEFAULT_CALIBRATION, n
    x = np.array([a for a, _r in rows], dtype=np.float64)
    a, b = DEFAULT_CALIBRATION
    for _ in range(2000):  # ridge-regularised logistic regression by gradient descent
        p = 1.0 / (1.0 + np.exp(-(a * x + b)))
        a -= 0.5 * (((p - y) * x).mean() + 1e-3 * a)
        b -= 0.5 * (p - y).mean()
    return (float(a), float(b)), n


# --- keyword ---------------------------------------------------------------
def _highlight(text, terms, terms_of, width=34):
    """A window of the passage around the first matched word, with matches marked [[like this]]."""
    words = text.split()
    hits = [i for i, w in enumerate(words) if any(t in terms for t in terms_of(w, keep_stop=True))]
    start = max(0, (hits[0] if hits else 0) - width // 3)
    window = [f"[[{w}]]" if i in set(hits) else w for i, w in enumerate(words)][start:start + width]
    return ("… " if start else "") + " ".join(window) + (" …" if start + width < len(words) else "")


def keyword_scores(lib, index, query, terms=None):
    """Best-chunk BM25 per document from the persistent text index.

    Returns {doc index: (score, chunk row, snippet)}. Text in double quotes
    must appear as a phrase.
    """
    phrases = [norm_name(p) for p in re.findall(r'"([^"]+)"', query)]
    terms = terms or tokens(query) or tokens(query, keep_stop=True)
    scores, matched = lib.text_index.search(terms)
    best = {}
    for chunk_id, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        row = index.chunk_row.get(chunk_id)
        if row is None:
            continue
        doc = int(index.chunk_doc[row])
        if doc in best:
            continue
        text = index.chunk_text[row]
        if phrases and not all(f" {p} " in f" {norm_name(text)} " for p in phrases if p):
            continue
        best[doc] = (score, row, _highlight(text, matched[chunk_id], lib.text_index.terms))
    return best


def _keyword_probability(score, lib, terms):
    """Heuristic: share of the best possible BM25 score, saturating.

    A passage containing every query term once scores about the sum of the
    terms' idf; that maps to roughly 0.8.
    """
    reference = sum(lib.text_index.idf(t) for t in dict.fromkeys(terms)) or 1.0
    return 1.0 - math.exp(-1.6 * max(0.0, score) / reference)


# --- semantic --------------------------------------------------------------
def semantic_scores(index, query):
    """Best-chunk cosine per document: (rescaled 0..1 array, raw cosine array, best chunk rows)."""
    n = len(index.docs)
    raw, best = np.zeros(n), np.full(n, -1, dtype=np.int64)
    if not len(index.chunk_text):
        return raw, raw, best
    sims = index.embeddings @ embed.embed_query(query)
    for row in np.argsort(-sims):
        doc = index.chunk_doc[row]
        if best[doc] < 0:
            best[doc], raw[doc] = row, sims[row]
    return np.clip((raw - SEM_FLOOR) / SEM_SPAN, 0.0, 1.0), raw, best


def _fan_out(index, query):
    """Rewordings of the query, each with one word swapped for the collection's closest word to it.

    Returns [(reworded query, similarity of the swapped word)].
    """
    out = []
    for t, written in dict(words(query)).items():
        near = vocabulary.neighbours(written, index.written)
        if near:
            word, similarity = index.written[near[0][0]], near[0][1]
            out.append((re.sub(r"[A-Za-z]+", lambda m: word if stem(m.group(0)) == t else m.group(0), query),
                        similarity))
    return out


# --- IAC ---------------------------------------------------------------------
def _query_properties(index, query):
    """External input for property units: [(kind, key, label, strength)]."""
    props, norm_q = [], " " + norm_name(query) + " "
    typed = dict(words(query))             # term -> the word as typed
    q_tokens = list(typed)
    # The query's words share a fixed budget of influence, split by rarity, so a
    # file matching two words of a two-word query outranks one matching two of
    # five. Words that occur in no document take their share with them.
    weight = {t: max(0.25, index.term_idf.get(t, 1.0)) for t in q_tokens}
    total = sum(weight.values())
    expanded = []
    for t in q_tokens:
        share = min(1.0, TERM_BUDGET * weight[t] / total)
        if t in index.term_links:
            props.append(("term", t, t, share))
        # fan the word out to collection words that mean nearly the same
        for word, similarity in vocabulary.neighbours(typed[t], index.written):
            if word not in q_tokens and all(word != e["key"] for e in expanded):
                expanded.append({"key": word, "term": index.written[word], "from": typed[t],
                                 "similarity": round(similarity, 3)})
                props.append(("term", word, f"{index.written[word]} (related to {typed[t]})",
                              share * (similarity - RELATED_FLOOR) / (1 - RELATED_FLOOR)))
    q_words, quoted = set(norm_q.split()), set()
    for e in index.entities.values():
        if not e["docs"]:
            continue
        if f" {e['norm']} " in norm_q:
            props.append(("entity", e["id"], e["value"], 1.0))
            if e["kind"] in REFERENCE_KINDS:
                quoted.update(tokens(e["value"]))
        elif e["kind"] in ("person", "org"):
            hit = [w for w in e["tokens"] if len(w) > 3 and w in q_words]
            if hit:
                props.append(("entity", e["id"], e["value"], 0.6 * len(hit) / len(e["tokens"])))
    for number in index.matters:
        for candidate in (number, index.matter_refs.get(number)):
            if candidate and len(norm_name(candidate)) > 2 and f" {norm_name(candidate)} " in norm_q:
                props.append(("matter", number, number, 1.0))
                quoted.update(tokens(candidate))
                break
    for doc_type in index.types:
        if f" {norm_name(doc_type)} " in norm_q:
            props.append(("type", doc_type, doc_type, 1.0))
    # A reference number has no meaning for the embedding model to match, so the part
    # of the query that is one takes its share of the semantic input away.
    prose = [t for t in q_tokens if t not in quoted and not any(c.isdigit() for c in t)]
    return props, q_tokens, (len(prose) / len(q_tokens) if q_tokens else 1.0), expanded


def _build_network(index, doc_rows, stimulated):
    """Assemble the weight matrix for the chosen documents and their properties.

    Unit order: documents, then terms, entities, matters, types.
    Returns (weights, pools, units) where units describes every property unit.
    """
    local = {d: i for i, d in enumerate(doc_rows)}
    n_docs = len(doc_rows)
    units = []  # (kind, key, label, {local doc: weight})

    def add(kind, key, label, links, strength=None):
        links = {local[d]: w * (strength or LINK[kind]) for d, w in links.items() if d in local and w > 0}
        if links:
            units.append((kind, key, label, links))

    stim = {(k, key) for k, key, _l, _s in stimulated}
    for kind, key, label, share in stimulated:
        if kind == "term":
            add(kind, key, label, {d: w * share for d, w in index.term_links[key].items()})
    for e in index.entities.values():
        # entities shared by several documents carry activation between them
        if ("entity", e["id"]) in stim or sum(1 for d in e["docs"] if d in local) >= 2:
            quoted = ("entity", e["id"]) in stim and e["kind"] in REFERENCE_KINDS
            add("entity", e["id"], e["value"], e["links"], LINK["reference"] if quoted else None)
    n_all = len(index.docs)
    for number, docs in index.matters.items():
        if len(docs) >= 2 or ("matter", number) in stim:
            add("matter", number, number, {d: max(0.15, _idf_norm(len(docs), n_all)) for d in docs},
                LINK["reference"] if ("matter", number) in stim else None)
    for doc_type, docs in index.types.items():
        add("type", doc_type, doc_type, {d: max(0.15, _idf_norm(len(docs), n_all)) for d in docs})

    size = n_docs + len(units)
    weights = np.zeros((size, size))
    for j, (_kind, _key, _label, links) in enumerate(units):
        col = n_docs + j
        for d, w in links.items():
            weights[d, col] = weights[col, d] = w

    pools = [(slice(0, n_docs), DOC_GAMMA)]
    start = n_docs
    for kind, competes in (("term", 0.0), ("entity", 0.0), ("matter", 1.0), ("type", 1.0)):
        count = sum(1 for u in units if u[0] == kind)
        pools.append((slice(start, start + count), competes))
        start += count
    return weights, pools, units


def iac_search(index, query, semantic):
    """Run the IAC network for a query. Returns per-document activations and an explanation."""
    stimulated, q_tokens, prose, expanded = _query_properties(index, query)
    typed = dict(words(query))
    semantic = semantic * prose
    n = len(index.docs)
    if n <= FULL_NETWORK_MAX_DOCS:
        doc_rows = list(range(n))
    else:
        seeds = set(np.argsort(-semantic)[:CANDIDATES].tolist())
        for kind, key, _l, _s in stimulated:
            links = (index.term_links[key] if kind == "term" else index.entities[key]["links"] if kind == "entity"
                     else dict.fromkeys(index.matters[key] if kind == "matter" else index.types[key], 1.0))
            seeds.update(sorted(links, key=links.get, reverse=True)[:CANDIDATES])
        doc_rows = sorted(seeds)
    weights, pools, units = _build_network(index, doc_rows, stimulated)
    n_docs = len(doc_rows)
    ext = np.zeros(len(weights))
    ext[:n_docs] = semantic[doc_rows]
    strength = {(k, key): s for k, key, _l, s in stimulated}
    for j, (kind, key, _label, _links) in enumerate(units):
        ext[n_docs + j] = strength.get((kind, key), 0.0)

    result = iac.settle(weights, pools, ext, IAC_PARAMS)
    act = result.activation
    out = np.maximum(act, 0.0)
    p = IAC_PARAMS
    doc_act = np.full(n, p.rest)
    doc_act[doc_rows] = act[:n_docs]

    # Why each document is active: its excitatory inputs at the settled state.
    reasons = defaultdict(list)
    for j, (kind, key, label, links) in enumerate(units):
        o = out[n_docs + j]
        if o <= 0:
            continue
        for d, w in links.items():
            reasons[doc_rows[d]].append({"kind": kind, "label": str(label), "input": round(p.alpha * w * o, 4),
                                         "in_query": (kind, key) in strength})
    for i, d in enumerate(doc_rows):
        if semantic[d] > 0:
            reasons[d].append({"kind": "semantic", "label": "meaning of query", "in_query": True,
                               "input": round(p.estr * float(semantic[d]), 4)})
        reasons[d].sort(key=lambda r: -r["input"])
    active_units = sorted(
        ({"kind": kind, "label": str(label), "activation": round(float(act[n_docs + j]), 3),
          "in_query": (kind, key) in strength} for j, (kind, key, label, _l) in enumerate(units)
         if act[n_docs + j] > 0.05), key=lambda u: -u["activation"])[:40]
    network = {"units": len(weights), "documents": n_docs, "cycles": result.cycles, "settled": result.settled,
               "active_units": active_units,
               "unknown_terms": [typed.get(t, t) for t in q_tokens if t not in index.term_links],
               "expanded": expanded,
               "params": {"max": p.max, "min": p.min, "rest": p.rest, "decay": p.decay, "estr": p.estr,
                          "alpha": p.alpha, "gamma": p.gamma, "doc_gamma_scale": DOC_GAMMA}}
    return doc_act, reasons, network


# --- public entry point ------------------------------------------------------
def _snippet(text, limit=260):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _reread(index, query, candidates, passages_of):
    """{doc index: the cross-encoder's verdict on its best passage}; {} if it is absent or abstains."""
    texts, owner = [], []
    for d in candidates:
        for row in passages_of(d):
            texts.append(index.chunk_text[row])
            owner.append(d)
    verdicts = rerank.scores(query, texts)
    if verdicts is None or verdicts.max() < RERANK_ABSTAIN:
        return {}
    best = {}
    for d, verdict in zip(owner, verdicts):
        best[d] = max(best.get(d, 0.0), float(verdict))
    return best


def search(query, mode="iac", limit=25, reread=True, also=()):
    """Search and return ranked possible matches with match probabilities.

    `also` is other wordings of the query (from the language model) to look for as well.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    query = (query or "").strip()
    with store.Session() as session:
        lib = session.lib
        index = get_index(lib)
        calibration = {"fitted": index.calibration != DEFAULT_CALIBRATION, "judgements": index.judgements,
                       "needed": MIN_JUDGEMENTS}
        if not query or not index.docs:
            return {"query": query, "mode": mode, "results": [], "p_none": 1.0, "network": None,
                    "calibration": calibration, "reread": 0, "also": []}
        keyword = keyword_scores(lib, index, query) if mode != "semantic" else {}
        q_terms = tokens(query) or tokens(query, keep_stop=True)
        p_keyword = np.array([_keyword_probability(keyword[d][0], lib, q_terms) if d in keyword else 0.0
                              for d in range(len(index.docs))])
        # passages to show for files found only through a related word
        fanned = [term for _t, written in words(query) for term, _s in vocabulary.neighbours(written, index.written)] \
            if mode == "iac" else []
        near = keyword_scores(lib, index, "", fanned) if fanned else {}

    n = len(index.docs)
    if mode != "keyword":
        semantic, cosine, sem_best = semantic_scores(index, query)
    else:
        semantic, cosine, sem_best = np.zeros(n), np.zeros(n), np.full(n, -1)

    network, reasons, activation = None, {}, None
    if mode == "keyword":
        score = np.array([keyword[d][0] if d in keyword else 0.0 for d in range(n)])
        probability = strength = p_keyword
    elif mode == "semantic":
        score, probability, strength = cosine, semantic, semantic
    elif mode == "hybrid":
        probability = 1.0 - (1.0 - p_keyword) * (1.0 - semantic)  # either kind of evidence can make a match
        score = strength = probability
    else:
        # a rewording counts for as much as its swapped word resembles the original
        for reworded, similarity in _fan_out(index, query) + [(wording, REWORDING) for wording in also]:
            semantic = np.maximum(semantic, similarity * semantic_scores(index, reworded)[0])
        activation, reasons, network = iac_search(index, query, semantic)
        a, b = index.calibration
        probability = np.array([_sigmoid(a * x + b) if x > 0 else 0.0 for x in activation])
        score = strength = activation

    # Relative probability: Luce choice rule over the matches plus a "none of these" alternative.
    share, p_none = iac.luce_choice(np.where(probability > 0, strength, 0.0))
    order = [int(d) for d in np.argsort(-score) if probability[d] > MIN_PROBABILITY]

    # Second reading: the cross-encoder reads the query against the best passages of the top results.
    first, verdicts = probability, {}
    if reread and mode in ("iac", "hybrid") and any(t.isalpha() for t in q_terms):
        def passages_of(d):
            rows = [keyword[d][1]] if d in keyword else [near[d][1]] if d in near else []
            return dict.fromkeys(rows + ([int(sem_best[d])] if sem_best[d] >= 0 else []))
        verdicts = _reread(index, query, order[:RERANK_TOP], passages_of)
        if verdicts:
            probability = probability.copy()
            for d, verdict in verdicts.items():
                p = min(max(float(first[d]), 1e-6), 1 - 1e-6)
                probability[d] = _sigmoid(math.log(p / (1 - p)) + RERANK_WEIGHT * (2 * verdict - 1))
            order.sort(key=lambda d: -probability[d])
    order = [d for d in order if probability[d] > MIN_PROBABILITY][:limit]

    results = []
    for d in order:
        doc = index.docs[d]
        if d in keyword:
            row, snippet = keyword[d][1], keyword[d][2]
        elif d in near:
            row, snippet = near[d][1], near[d][2]
        elif sem_best[d] >= 0:
            row, snippet = int(sem_best[d]), _snippet(index.chunk_text[int(sem_best[d])])
        else:
            row, snippet = None, ""
        results.append({
            "id": doc["id"], "filename": doc["filename"], "title": doc["title"], "doc_type": doc["doc_type"],
            "doc_date": doc["doc_date"], "matter": doc["matter"], "page_count": doc["page_count"],
            "flags": doc["flags"],
            "score": round(float(score[d]), 4),
            "probability": round(float(probability[d]), 4),
            "first_probability": round(float(first[d]), 4),
            "reread": round(verdicts[d], 3) if d in verdicts else None,
            "share": round(float(share[d]), 4),
            "keyword_score": round(float(keyword[d][0]), 3) if d in keyword else None,
            "semantic_score": round(float(cosine[d]), 3) if mode != "keyword" else None,
            "activation": round(float(activation[d]), 4) if activation is not None else None,
            "page": index.chunk_page[row] if row is not None else None,
            "snippet": snippet,
            "matched_text": d in keyword,
            "why": reasons.get(d, [])[:6],
        })
    return {"query": query, "mode": mode, "results": results, "p_none": round(float(p_none), 4),
            "network": network, "calibration": calibration,
            "reread": sum(r["reread"] is not None for r in results), "also": list(also)}


def passages(query, limit=5, per_document=2):
    """The passages most likely to answer a question, best first, for the language model to read.

    Candidates come from the keyword index and from the embeddings; the
    cross-encoder then picks among them (without it, the embedding order stands).
    """
    query = (query or "").strip()
    with store.Session() as session:
        lib = session.lib
        index = get_index(lib)
        if not query or not len(index.chunk_text):
            return []
        scores, _matched = lib.text_index.search(tokens(query))
        by_keyword = [index.chunk_row[c] for c, _s in sorted(scores.items(), key=lambda kv: -kv[1])[:20]
                      if c in index.chunk_row]
    similarity = index.embeddings @ embed.embed_query(query)
    rows = list(dict.fromkeys(np.argsort(-similarity)[:20].tolist() + by_keyword))
    verdicts = rerank.scores(query, [index.chunk_text[r] for r in rows])
    score = {r: float(verdicts[i]) if verdicts is not None else float(similarity[r]) for i, r in enumerate(rows)}
    out, taken, seen = [], Counter(), set()
    for row in sorted(rows, key=lambda r: -score[r]):
        doc = index.docs[int(index.chunk_doc[row])]
        text = " ".join(index.chunk_text[row].split())
        if taken[doc["id"]] >= per_document or text in seen:    # copies of a page say nothing new
            continue
        taken[doc["id"]] += 1
        seen.add(text)
        out.append({"id": doc["id"], "title": doc["title"], "filename": doc["filename"], "matter": doc["matter"],
                    "page": index.chunk_page[row], "text": text, "score": round(score[row], 3)})
        if len(out) == limit:
            break
    return out


def related(lib, doc, limit=8):
    """Documents sharing people, organisations or references with this one, rarest links first."""
    n = max(2, len(lib.documents))
    scores, shared = Counter(), defaultdict(list)
    for mention in doc.mentions:
        entity = mention.entity
        weight = _idf_norm(len(entity.documents), n)
        if weight <= 0:
            continue
        for other in entity.documents.values():
            if other is not doc:
                scores[other.id] += weight
                shared[other.id].append(entity.value)
    out = []
    for other_id, score in scores.most_common(limit):
        if score < 0.3:
            break
        other = lib.documents[other_id]
        out.append({"id": other.id, "title": other.title, "filename": other.filename, "matter": other.matter,
                    "score": round(score, 3), "shared": shared[other_id][:6]})
    return out
