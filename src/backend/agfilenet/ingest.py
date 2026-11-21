"""Ingest pipeline: read files, OCR where needed, derive metadata, index for search."""
import hashlib
import re
import threading
from datetime import datetime, timezone
from urllib.parse import unquote

from . import config, embed, extract, metadata, store, workbook
from .textutil import chunk_text, norm_name, tokens

LOW_OCR_CONF = 0.85
DUP_JACCARD = 0.8
DUP_MIN_TOKENS = 25
ORG_WORDS = re.compile(r"ministry|authority|attorney|commissioner|police|limited|ltd|bank|"
                       r"government|c\.?o\.?p|regina|queen|office|company", re.I)

_job_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def discover():
    """Source documents under the data directory."""
    return [p for p in sorted(config.DATA_DIR.rglob("*"))
            if p.is_file() and p.suffix.lower() in config.DOC_EXTENSIONS and "__MACOSX" not in p.parts]


def _load_workbooks(lib):
    """Store the declared matters; return {(package, filename): declared document fields}."""
    declared = {}
    for path in sorted(config.DATA_DIR.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        package = path.relative_to(config.DATA_DIR).parts[0]
        data = workbook.read_workbook(path)
        for number, m in data["matters"].items():
            matter = lib.matters.get(number)
            if matter is None:
                matter = lib.matters[number] = store.Matter(number)
            matter.title, matter.reference = m["title"], m["reference"]
            matter.package, matter.parties = package, list(m["parties"])
        for name, d in data["documents"].items():
            m = data["matters"].get(d["matter"], {})
            declared[(package, name)] = {**d, "matter_title": m.get("title"), "reference": m.get("reference")}
    return declared


def _read_file(lib, path, declared, tick):
    """Create or refresh the Document for one file, reading its pages if it is new or changed."""
    rel = path.relative_to(config.DATA_DIR)
    doc = lib.by_path.get(str(rel)) or lib.add_document(str(rel), path.name)
    sha = _sha256(path)
    unchanged = doc.sha256 == sha and doc.status == "ok"
    decl = declared.get((rel.parts[0] if len(rel.parts) > 1 else None, path.name), {})
    doc.package = rel.parts[0] if len(rel.parts) > 1 else None
    doc.folder = unquote(path.parent.name)
    doc.sha256, doc.size = sha, path.stat().st_size
    doc.content_type = extract.CONTENT_TYPES.get(path.suffix.lower())
    doc.decl_matter, doc.decl_matter_title = decl.get("matter"), decl.get("matter_title")
    doc.decl_reference, doc.decl_doc_type = decl.get("reference"), decl.get("doc_type")
    doc.decl_comments = decl.get("comments")
    if unchanged:
        for _ in doc.pages:
            tick()
        return
    lib.clear_chunks(doc)
    del doc.pages[:]
    try:
        for p in extract.extract_pages(path, progress=tick):
            doc.pages.append(store.Page(doc, p["page_no"], p["text"], p["source"], p["ocr_conf"], p["rotation"]))
        sources = {p.source for p in doc.pages}
        confs = [p.ocr_conf for p in doc.pages if p.ocr_conf is not None]
        doc.text_source = "mixed" if len(sources) > 1 else next(iter(sources), None)
        doc.ocr_conf = round(sum(confs) / len(confs), 4) if confs else None
        doc.status, doc.error, doc.ingested_at = "ok", None, now()
    except Exception as exc:  # a broken file must not stop the batch
        del doc.pages[:]
        doc.status, doc.error = "error", repr(exc)[:500]


def _mark_duplicate_pages(docs):
    """Point every page at the first earlier page with near-identical text."""
    seen = []
    for doc in docs:
        for page in doc.pages:
            toks = frozenset(tokens(page.text or ""))
            dup = None
            if len(toks) >= DUP_MIN_TOKENS:
                for other, other_toks in seen:
                    if 0.7 < len(toks) / len(other_toks) < 1.43 and \
                            len(toks & other_toks) / len(toks | other_toks) >= DUP_JACCARD:
                        dup = other
                        break
                seen.append((page, toks))
            if page.dup_of is not dup:
                page.dup_of = dup


def _normalise_type(value):
    return re.sub(r"[^a-z]", "", (value or "").lower())


def _same_type(declared, derived):
    """'Demand Mortgage' and 'Mortgage', or 'File Title' and 'File Cover', are the same finding."""
    a, b = (_normalise_type(v).replace("filetitle", "filecover") for v in (declared, derived))
    return a in b or b in a


def analyse(lib):
    """Derive metadata for every ingested document from its stored page text."""
    docs = lib.ok_documents()
    _mark_duplicate_pages(docs)
    lib.clear_entities()
    sha_seen, results = set(), []

    for doc in docs:
        pages = []
        for page in doc.pages:
            page.page_type, _conf, page.is_start = metadata.classify_page(page.text or "")
            pages.append({"page_no": page.page_no, "text": page.text, "page_type": page.page_type,
                          "is_start": page.is_start})
        typed = [(p.page_no, p.page_type, p.is_start, p.dup_of is not None and p.dup_of.document is doc)
                 for p in doc.pages]
        segments = metadata.segment_pages(typed)
        del doc.segments[:]
        doc.segments.extend(store.Segment(*s) for s in segments)
        matter = lib.matters.get(doc.decl_matter)
        meta = metadata.extract_document(pages, matter.parties if matter is not None else ())
        if meta["doc_type"] == "File Cover" and doc.decl_matter_title:
            meta["title"] = f"File Cover: {doc.decl_matter_title}"  # covers are handwritten

        flags = set(meta["flags"])
        if len(segments) > 1:
            flags.add("bundle")
        if any(p.dup_of is not None for p in doc.pages):
            flags.add("duplicate-pages")
        if any(p.rotation for p in doc.pages):
            flags.add("rotated-pages")
        if doc.ocr_conf is not None and doc.ocr_conf < LOW_OCR_CONF:
            flags.add("low-ocr-confidence")
        if doc.sha256 in sha_seen:
            flags.add("duplicate-file")
        sha_seen.add(doc.sha256)
        if not doc.decl_matter:
            flags.add("not-in-workbook")
        elif not doc.decl_doc_type:
            flags.add("no-declared-type")
        elif meta["doc_type"] and not _same_type(doc.decl_doc_type, meta["doc_type"]):
            flags.add("type-differs")

        doc.flags = sorted(flags)
        doc.parties = [tuple(p) for p in meta["parties"]]
        doc.doc_type_conf = meta["doc_type_conf"]
        if not doc.edited:  # manual corrections win over derived values
            doc.title, doc.doc_type, doc.doc_date = meta["title"], meta["doc_type"], meta["doc_date"]
            doc.subject = meta["subject"]
            doc.matter = doc.decl_matter or doc.folder
        results.append((doc, meta))

    # Names found anywhere (court headings, titled names, workbook parties) are
    # then looked for in every document, so untitled mentions still link up.
    gazetteer = {}
    for _doc, meta in results:
        for kind, value, _page in meta["entities"]:
            if kind in ("person", "party") and len(value.split()) >= 2:
                gazetteer.setdefault(norm_name(value), value)
    for matter in lib.matters.values():
        for name in matter.parties:
            if len(name.split()) >= 2:
                gazetteer.setdefault(norm_name(name), name)

    for doc, meta in results:
        found = {}  # (kind, norm) -> [value, count, first page]

        def note(kind, value, page_no):
            norm = norm_name(value)
            if len(norm) >= 3:
                found.setdefault((kind, norm), [value, 0, page_no])[1] += 1

        for kind, value, page_no in meta["entities"]:
            if kind == "party":
                kind = "org" if ORG_WORDS.search(value) else "person"
            note(kind, value, page_no)
        for page in doc.pages:
            text = " " + norm_name(page.text or "") + " "
            for norm, value in gazetteer.items():
                if f" {norm} " in text:
                    note("org" if ORG_WORDS.search(value) else "person", value, page.page_no)
        for (kind, norm), (value, count, first_page) in found.items():
            lib.link(doc, lib.entity(kind, value, norm), count, first_page)
    lib.touch()


def index_chunks(lib, commit=None):
    """Chunk and embed the pages of documents that have no chunks yet."""
    for doc in lib.ok_documents():
        if len(doc.chunks):
            continue
        items = [(p.page_no, c) for p in doc.pages for c in chunk_text(p.text or "")]
        if items:
            vectors = embed.embed_passages([c for _n, c in items])
            for (page_no, text), vector in zip(items, vectors):
                lib.add_chunk(doc, page_no, text, vector.tobytes())
        if commit:
            commit()
    lib.touch()


def run(force=False, job_id=None):
    """Run the whole pipeline. Safe to re-run: unchanged files are not re-read."""
    if not _job_lock.acquire(blocking=False):
        raise RuntimeError("an ingest job is already running")
    session = store.Session()
    lib = session.lib
    job = lib.jobs.get(job_id) if job_id else None

    def status(**fields):
        if job is not None:
            for key, value in fields.items():
                setattr(job, key, value)
        session.commit()

    try:
        declared = _load_workbooks(lib)
        files = discover()
        known = {str(p.relative_to(config.DATA_DIR)) for p in files}
        for doc in list(lib.documents.values()):
            if doc.path not in known:
                lib.remove_document(doc)
            elif force:
                doc.status = "new"
        total = sum(extract.count_pages(p) for p in files)
        done = [0]
        status(status="running", total=total, done=0, message="Reading pages")

        def tick():
            done[0] += 1
            if job is not None and done[0] % 5 == 0:
                job.done = done[0]
                session.commit()  # progress; a half-read file stays 'new' and is re-read next run

        for i, path in enumerate(files):
            status(message=f"Reading {path.name} ({i + 1}/{len(files)})")
            _read_file(lib, path, declared, tick)
            status(done=done[0])
        status(message="Deriving metadata", done=total)
        analyse(lib)
        status(message="Building search index")
        index_chunks(lib, session.commit)
        status(status="done", message=f"Ingested {len(files)} files, {total} pages", finished=now())
        store.database().pack()
    except Exception as exc:
        session.abort()
        status(status="error", message=repr(exc)[:500], finished=now())
        raise
    finally:
        session.abort()
        session.conn.close()
        _job_lock.release()


def new_job():
    with store.Session(write=True) as s:
        job = store.Job(s.lib.next_id("job"), now())
        s.lib.jobs[job.id] = job
        return job.id


def running():
    return _job_lock.locked()


def start_job(force=False):
    if running():
        with store.Session() as s:
            return s.lib.latest_job().id
    job_id = new_job()
    threading.Thread(target=run, kwargs={"force": force, "job_id": job_id}, daemon=True).start()
    return job_id
