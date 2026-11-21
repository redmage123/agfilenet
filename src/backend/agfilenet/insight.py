"""What the embeddings say about each file as a whole: a summary, a topic and a likely type.

All three work from the passage embeddings made at indexing time.

* Summary: the sentences of the file closest in meaning to the file as a
  whole (extractive: every word of it is the document's own).
* Topic: files are grouped by meaning (k-means on their mean embedding) and
  each group is named after the words that set it apart.
* Suggested type: the type of the most similar files whose type is known.
  Types corrected by hand count double, so the suggestions follow the
  corrections people make.
"""
import math
import re
from collections import Counter

import numpy as np

from . import embed
from .textutil import STOPWORDS, is_word, tokens

SUMMARY_SENTENCES = 2
MAX_SENTENCES = 80          # per file; later sentences are rarely what the file is about
NEIGHBOURS = 5
MIN_SUGGESTION = 0.5
TRUSTED_RULE = 0.75         # a rule-derived type this confident is used as an example
MAX_TOPICS = 12

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])|\n{2,}")


def _vector(doc):
    """(mean embedding of the file, embedding of its opening passage), unit length; None without passages."""
    if not len(doc.chunks):
        return None
    vectors = np.frombuffer(b"".join(c.embedding for c in doc.chunks), dtype=np.float32).reshape(len(doc.chunks), -1)
    mean = vectors.mean(axis=0)
    return mean / (np.linalg.norm(mean) or 1.0), vectors[0]


# --- summary -------------------------------------------------------------------
def _sentences(doc):
    out = []
    for page in doc.pages:
        if page.dup_of is not None:
            continue
        for raw in _SENTENCE.split(page.text or ""):
            lines = raw.strip().split("\n")
            while len(lines) > 1 and not any(c.islower() for c in lines[0]):
                lines.pop(0)                # a heading that ran into the sentence below it
            sentence = " ".join(" ".join(lines).split())
            words = re.findall(r"[A-Za-z]+", sentence)
            # prose only: headings, address blocks and badly read lines do not summarise anything
            if 8 <= len(words) <= 60 and sum(w.isupper() for w in words) < 0.5 * len(words) \
                    and sum(w[0].isupper() or is_word(w.lower()) for w in words) >= 0.85 * len(words) \
                    and sum(is_word(w.lower()) for w in words) >= 0.6 * len(words):
                out.append(sentence)
    return list(dict.fromkeys(out))[:MAX_SENTENCES]


def summarise(doc, mean):
    sentences = _sentences(doc)
    if len(sentences) <= SUMMARY_SENTENCES:
        return " ".join(sentences) or None
    vectors = embed.embed_passages(sentences)
    central = vectors @ mean
    chosen = []
    for _ in range(SUMMARY_SENTENCES):
        # the most central sentence that does not repeat one already chosen
        penalty = np.max(vectors @ vectors[chosen].T, axis=1) if chosen else 0.0
        score = central - 0.5 * penalty
        score[chosen] = -np.inf
        chosen.append(int(np.argmax(score)))
    return " ".join(sentences[i] for i in sorted(chosen))


# --- topics --------------------------------------------------------------------
def _kmeans(vectors, k):
    """Spherical k-means with a fixed start (farthest-point), so the same files give the same groups."""
    centres = [vectors[int(np.argmax(vectors @ vectors.mean(axis=0)))]]
    while len(centres) < k:
        centres.append(vectors[int(np.argmin(np.max(vectors @ np.array(centres).T, axis=1)))])
    centres = np.array(centres)
    labels = None
    for _ in range(50):
        new = np.argmax(vectors @ centres.T, axis=1)
        if labels is not None and (new == labels).all():
            break
        labels = new
        for j in range(k):
            members = vectors[labels == j]
            if len(members):
                centre = members.mean(axis=0)
                centres[j] = centre / (np.linalg.norm(centre) or 1.0)
    return labels


def _topic_labels(docs, labels, lib):
    """Name each group by the dictionary words most of its files use and other files do not."""
    words = []
    for doc in docs:
        seen = Counter()
        for chunk in doc.chunks:
            seen.update(t for t in lib.text_index.terms(chunk.text) if len(t) > 3 and t.isalpha() and is_word(t)
                        and t not in STOPWORDS)
        words.append(seen)
    overall = Counter(t for seen in words for t in seen)
    names = {}
    for group in sorted(set(labels)):
        members = [i for i, g in enumerate(labels) if g == group]
        inside = Counter(t for i in members for t in words[i])
        score = {t: (c / len(members)) * math.log((len(docs) + 1) / (overall[t] - c + 1))
                 for t, c in inside.items() if c >= min(2, len(members))}
        often = Counter()
        for i in members:
            often.update(words[i])
        best = sorted(score, key=lambda t: (-round(score[t], 6), -often[t], t))[:3]
        names[group] = ", ".join(best) or f"Group {group + 1}"
    return names


def assign_topics(lib, docs, means):
    if len(docs) < 3:
        for doc in docs:
            doc.topic = None
        return
    k = min(MAX_TOPICS, max(2, round(math.sqrt(len(docs) / 2))))
    # Files of one collection all resemble each other; what they have in common is
    # taken out first so that the grouping is by what sets them apart.
    apart = means - means.mean(axis=0)
    apart /= np.maximum(np.linalg.norm(apart, axis=1, keepdims=True), 1e-9)
    labels = _kmeans(apart, k).tolist()
    names = _topic_labels(docs, labels, lib)
    for doc, group in zip(docs, labels):
        if doc.topic != names[group]:
            doc.topic = names[group]


# --- type suggestion -------------------------------------------------------------
def suggest_types(docs, means, openings):
    """Give every file the type its nearest typed neighbours have, where that differs from its own."""
    features = 0.6 * openings + 0.4 * means       # the opening passage says most about what kind of paper it is
    features /= np.linalg.norm(features, axis=1, keepdims=True)
    examples = [(i, d.doc_type, 2.0 if d.edited else 1.0) for i, d in enumerate(docs)
                if d.doc_type and (d.edited or (d.doc_type_conf or 0) >= TRUSTED_RULE)]
    for i, doc in enumerate(docs):
        suggestion = confidence = None
        near = sorted(((float(features[i] @ features[j]), label, weight) for j, label, weight in examples if j != i),
                      reverse=True)[:NEIGHBOURS]
        if near and not doc.edited:
            votes = Counter()
            for similarity, label, weight in near:
                votes[label] += weight * max(0.0, similarity - 0.5)
            label, vote = votes.most_common(1)[0]
            total = sum(votes.values())
            # agreement among the neighbours, tempered by how close the closest of them is
            closest = max(s for s, lab, _w in near if lab == label)
            score = (vote / total if total else 0.0) * min(1.0, max(0.0, (closest - 0.6) / 0.3))
            if label != doc.doc_type and score >= MIN_SUGGESTION:
                suggestion, confidence = label, round(score, 3)
        if (doc.suggested_type, doc.suggested_conf) != (suggestion, confidence):
            doc.suggested_type, doc.suggested_conf = suggestion, confidence


def refresh(lib, summaries=True):
    """Bring summaries, topics and type suggestions up to date with the indexed passages."""
    docs, means, openings = [], [], []
    for doc in lib.ok_documents():
        vectors = _vector(doc)
        if vectors is None:
            doc.summary = doc.topic = doc.suggested_type = doc.suggested_conf = None
            continue
        docs.append(doc)
        means.append(vectors[0])
        openings.append(vectors[1])
        if summaries and doc.summary_of != doc.sha256:
            doc.summary, doc.summary_of = summarise(doc, vectors[0]), doc.sha256
    if docs:
        means, openings = np.array(means), np.array(openings)
        assign_topics(lib, docs, means)
        suggest_types(docs, means, openings)
    lib.touch()
