"""Object database (ZODB) holding everything the application knows.

Metadata is stored as a graph of persistent objects rather than rows:
a Library owns Documents, a Document owns its Pages, Segments and Chunks,
and Documents, Entities and Matters reference each other directly. Lookups
that are not plain traversal go through BTrees kept on the Library, and
keyword retrieval goes through the persistent TextIndex.
"""
import math
import threading
from collections import defaultdict

import transaction
import ZODB
import ZODB.FileStorage
from BTrees.IIBTree import IIBTree
from BTrees.IOBTree import IOBTree
from BTrees.OOBTree import OOBTree
from persistent import Persistent
from persistent.list import PersistentList

from . import config
from .textutil import tokens


class Page(Persistent):
    def __init__(self, document, page_no, text, source, ocr_conf=None, rotation=0):
        self.document = document
        self.page_no = page_no
        self.text = text
        self.source = source            # 'text' (PDF text layer) or 'ocr'
        self.ocr_conf = ocr_conf
        self.rotation = rotation
        self.page_type = None
        self.is_start = False
        self.dup_of = None              # the earlier Page with the same content, if any


class Segment(Persistent):
    """A run of pages inside one file that looks like a separate document."""

    def __init__(self, start_page, end_page, doc_type):
        self.start_page = start_page
        self.end_page = end_page
        self.doc_type = doc_type


class Chunk(Persistent):
    """A passage of page text with its embedding; the unit that search retrieves."""

    def __init__(self, chunk_id, document, page_no, text, embedding):
        self.id = chunk_id
        self.document = document
        self.page_no = page_no
        self.text = text
        self.embedding = embedding      # float32 bytes


class Mention(Persistent):
    def __init__(self, entity, count, first_page):
        self.entity = entity
        self.count = count
        self.first_page = first_page


class Entity(Persistent):
    """A person, organisation, case number, file reference or registry volume."""

    def __init__(self, entity_id, kind, value, norm):
        self.id = entity_id
        self.kind = kind
        self.value = value
        self.norm = norm
        self.documents = IOBTree()      # document id -> Document


class Matter(Persistent):
    """A matter as declared in a migration workbook."""

    def __init__(self, number):
        self.number = number
        self.title = None
        self.reference = None
        self.package = None
        self.parties = []


class Document(Persistent):
    def __init__(self, doc_id, path, filename):
        self.id = doc_id
        self.path = path                # relative to the data directory
        self.filename = filename
        self.package = None             # top-level folder under data/
        self.folder = None              # immediate parent folder (URL-decoded)
        self.sha256 = None
        self.size = None
        self.content_type = None
        self.text_source = None         # 'text', 'ocr' or 'mixed'
        self.ocr_conf = None
        self.status = "new"             # new | ok | error
        self.error = None
        self.ingested_at = None
        # derived metadata
        self.title = None
        self.doc_type = None
        self.doc_type_conf = None
        self.doc_date = None
        self.subject = None
        self.parties = []               # [(name, role)]
        self.matter = None
        self.flags = []
        self.edited = False
        # metadata declared in the migration workbook, if any
        self.decl_matter = None
        self.decl_matter_title = None
        self.decl_reference = None
        self.decl_doc_type = None
        self.decl_comments = None
        # owned objects
        self.pages = PersistentList()
        self.segments = PersistentList()
        self.chunks = PersistentList()
        self.mentions = PersistentList()

    @property
    def page_count(self):
        return len(self.pages)


class Job(Persistent):
    def __init__(self, job_id, started):
        self.id = job_id
        self.status = "queued"
        self.total = 0
        self.done = 0
        self.message = "Starting"
        self.started = started
        self.finished = None


class Judgement(Persistent):
    """A user's verdict on one search result, used to calibrate match probabilities."""

    def __init__(self, query, document, activation, relevant, created):
        self.query = query
        self.document = document
        self.activation = activation
        self.relevant = relevant
        self.created = created


class TextIndex(Persistent):
    """Inverted index over chunks with Okapi BM25 ranking."""

    K1, B = 1.2, 0.75

    def __init__(self):
        self.postings = OOBTree()       # term -> IIBTree {chunk id: term frequency}
        self.lengths = IIBTree()        # chunk id -> number of indexed tokens
        self.total_length = 0

    def add(self, chunk_id, text):
        counts = defaultdict(int)
        for t in tokens(text):
            counts[t] += 1
        for term, tf in counts.items():
            posting = self.postings.get(term)
            if posting is None:
                posting = self.postings[term] = IIBTree()
            posting[chunk_id] = tf
        length = sum(counts.values())
        self.lengths[chunk_id] = length
        self.total_length += length

    def remove(self, chunk_id, text):
        if chunk_id not in self.lengths:
            return
        for term in set(tokens(text)):
            posting = self.postings.get(term)
            if posting is not None and chunk_id in posting:
                del posting[chunk_id]
                if not posting:
                    del self.postings[term]
        self.total_length -= self.lengths[chunk_id]
        del self.lengths[chunk_id]

    def idf(self, term):
        n, df = len(self.lengths), len(self.postings.get(term, ()))
        return math.log(1 + (n - df + 0.5) / (df + 0.5)) if df else 0.0

    def search(self, terms):
        """Return ({chunk id: BM25 score}, {chunk id: set of matched terms})."""
        n = len(self.lengths)
        if not n:
            return {}, {}
        average = self.total_length / n or 1.0
        scores, matched = defaultdict(float), defaultdict(set)
        for term in dict.fromkeys(terms):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = self.idf(term)
            for chunk_id, tf in posting.items():
                norm = tf + self.K1 * (1 - self.B + self.B * self.lengths[chunk_id] / average)
                scores[chunk_id] += idf * tf * (self.K1 + 1) / norm
                matched[chunk_id].add(term)
        return scores, matched


class Library(Persistent):
    """Root object of the database."""

    def __init__(self):
        self.documents = IOBTree()      # id -> Document
        self.by_path = OOBTree()        # relative path -> Document
        self.entities = OOBTree()       # (kind, norm) -> Entity
        self.matters = OOBTree()        # matter number -> Matter
        self.chunks = IOBTree()         # id -> Chunk
        self.jobs = IOBTree()           # id -> Job
        self.judgements = OOBTree()     # (query, document id) -> Judgement
        self.text_index = TextIndex()
        self.counters = OOBTree()
        self.revision = 0               # bumped whenever searchable content changes

    def next_id(self, kind):
        value = self.counters.get(kind, 0) + 1
        self.counters[kind] = value
        return value

    def touch(self):
        self.revision += 1

    # documents
    def add_document(self, path, filename):
        doc = Document(self.next_id("document"), path, filename)
        self.documents[doc.id] = doc
        self.by_path[path] = doc
        return doc

    def remove_document(self, doc):
        self.clear_chunks(doc)
        for mention in doc.mentions:
            mention.entity.documents.pop(doc.id, None)
        for key in [k for k, j in self.judgements.items() if j.document is doc]:
            del self.judgements[key]
        del self.documents[doc.id]
        del self.by_path[doc.path]

    def ok_documents(self):
        return [d for d in self.documents.values() if d.status == "ok"]

    # chunks
    def add_chunk(self, doc, page_no, text, embedding):
        chunk = Chunk(self.next_id("chunk"), doc, page_no, text, embedding)
        doc.chunks.append(chunk)
        self.chunks[chunk.id] = chunk
        self.text_index.add(chunk.id, text)
        return chunk

    def clear_chunks(self, doc):
        for chunk in doc.chunks:
            self.text_index.remove(chunk.id, chunk.text)
            self.chunks.pop(chunk.id, None)
        del doc.chunks[:]

    # entities
    def clear_entities(self):
        self.entities.clear()
        for doc in self.documents.values():
            del doc.mentions[:]

    def entity(self, kind, value, norm):
        entity = self.entities.get((kind, norm))
        if entity is None:
            entity = self.entities[(kind, norm)] = Entity(self.next_id("entity"), kind, value, norm)
        return entity

    def link(self, doc, entity, count, first_page):
        doc.mentions.append(Mention(entity, count, first_page))
        entity.documents[doc.id] = doc

    def latest_job(self):
        return self.jobs[self.jobs.maxKey()] if len(self.jobs) else None


# --- connections -------------------------------------------------------------
_db = None
_db_path = None
_db_lock = threading.Lock()


def database():
    """The process-wide ZODB database for the configured path."""
    global _db, _db_path
    with _db_lock:
        if _db is None or _db_path != config.DB_PATH:
            if _db is not None:
                _db.close()
            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _db = ZODB.DB(ZODB.FileStorage.FileStorage(str(config.DB_PATH)))
            _db_path = config.DB_PATH
            with _db.transaction() as conn:
                if not hasattr(conn.root, "library"):
                    conn.root.library = Library()
        return _db


def close():
    global _db, _db_path
    with _db_lock:
        if _db is not None:
            _db.close()
        _db = _db_path = None


class Session:
    """One connection with its own transaction; use as a context manager.

    Reads see a consistent snapshot. Changes are saved by commit(), or on a
    clean exit when opened with write=True; otherwise they are discarded.
    """

    def __init__(self, write=False):
        self.write = write
        self.tm = transaction.TransactionManager()
        self.conn = database().open(self.tm)
        self.lib = self.conn.root.library

    def commit(self):
        self.tm.commit()

    def abort(self):
        self.tm.abort()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None and self.write:
                self.tm.commit()
            else:
                self.tm.abort()
        finally:
            self.conn.close()
        return False
