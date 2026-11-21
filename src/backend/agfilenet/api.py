"""HTTP API and static hosting for the React front end."""
import csv
import io
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, extract, ingest, search, store

app = FastAPI(title="AG FileNet migration workbench")

EDITABLE = ("title", "doc_type", "doc_date", "subject", "matter")
SUMMARY_FIELDS = ("id", "filename", "path", "package", "folder", "size", "content_type", "page_count",
                  "text_source", "ocr_conf", "status", "error", "title", "doc_type", "doc_type_conf", "doc_date",
                  "subject", "matter", "edited", "decl_matter", "decl_matter_title", "decl_reference",
                  "decl_doc_type", "decl_comments", "sha256")


def _summary(doc):
    out = {field: getattr(doc, field) for field in SUMMARY_FIELDS}
    out["flags"] = list(doc.flags)
    out["parties"] = [list(p) for p in doc.parties]
    return out


def _get_doc(lib, doc_id):
    doc = lib.documents.get(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


def _source_path(doc):
    path = (config.DATA_DIR / doc.path).resolve()
    if config.DATA_DIR not in path.parents or not path.is_file():
        raise HTTPException(404, "source file is missing")
    return path


def _job(job):
    return None if job is None else {k: getattr(job, k) for k in
                                     ("id", "status", "total", "done", "message", "started", "finished")}


def _flag_counts(lib):
    counts = {}
    for doc in lib.documents.values():
        for flag in doc.flags:
            counts[flag] = counts.get(flag, 0) + 1
    return counts


@app.get("/api/status")
def status():
    with store.Session() as s:
        lib = s.lib
        docs = list(lib.documents.values())
        job = _job(lib.latest_job())
        if job and job["status"] in ("queued", "running") and not ingest.running():
            job["status"], job["message"] = "interrupted", "Interrupted - run ingest again to resume"
        return {
            "data_dir": str(config.DATA_DIR), "files_found": len(ingest.discover()),
            "counts": {"documents": len(docs), "pages": sum(d.page_count for d in docs),
                       "errors": sum(d.status == "error" for d in docs),
                       "untyped": sum(d.doc_type is None for d in docs),
                       "undeclared_type": sum(d.decl_doc_type is None for d in docs),
                       "edited": sum(bool(d.edited) for d in docs)},
            "flags": _flag_counts(lib), "entities": len(lib.entities),
            "duplicate_pages": sum(p.dup_of is not None for d in docs for p in d.pages),
            "job": job}


class IngestRequest(BaseModel):
    force: bool = False


@app.post("/api/ingest")
def start_ingest(body: IngestRequest = IngestRequest()):
    return {"job_id": ingest.start_job(force=body.force)}


@app.get("/api/facets")
def facets():
    with store.Session() as s:
        docs = list(s.lib.documents.values())

        def group(field):
            counts = {}
            for d in docs:
                value = getattr(d, field)
                if value is not None:
                    counts[value] = counts.get(value, 0) + 1
            return [{"value": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        return {"doc_type": group("doc_type"), "matter": group("matter"), "package": group("package"),
                "flag": [{"value": k, "count": v}
                         for k, v in sorted(_flag_counts(s.lib).items(), key=lambda kv: -kv[1])]}


@app.get("/api/documents")
def list_documents(doc_type: Optional[str] = None, matter: Optional[str] = None, package: Optional[str] = None,
                   flag: Optional[str] = None, q: Optional[str] = None):
    with store.Session() as s:
        out = []
        for doc in s.lib.documents.values():
            if any(value and (getattr(doc, field) is not None if value == "(none)" else getattr(doc, field) != value)
                   for field, value in (("doc_type", doc_type), ("matter", matter), ("package", package))):
                continue
            if flag and flag not in doc.flags:
                continue
            if q and not any(q.lower() in (getattr(doc, f) or "").lower() for f in ("title", "filename", "matter")):
                continue
            out.append(_summary(doc))
        return sorted(out, key=lambda d: (d["package"] or "", d["folder"] or "", d["filename"]))


def _detail(lib, doc):
    out = _summary(doc)
    copies = {}
    for other in lib.documents.values():
        if other is not doc:
            count = sum(1 for p in other.pages if p.dup_of is not None and p.dup_of.document is doc)
            if count:
                copies[other.id] = {"id": other.id, "filename": other.filename, "title": other.title, "pages": count}
    out.update(
        pages=[{"page_no": p.page_no, "text": p.text, "source": p.source, "ocr_conf": p.ocr_conf,
                "rotation": p.rotation, "page_type": p.page_type, "is_start": p.is_start,
                "dup_doc_id": p.dup_of.document.id if p.dup_of is not None else None,
                "dup_page_no": p.dup_of.page_no if p.dup_of is not None else None,
                "dup_filename": p.dup_of.document.filename if p.dup_of is not None else None}
               for p in doc.pages],
        segments=[{"start_page": g.start_page, "end_page": g.end_page, "doc_type": g.doc_type}
                  for g in doc.segments],
        entities=sorted(({"kind": m.entity.kind, "value": m.entity.value, "count": m.count,
                          "first_page": m.first_page, "docs": len(m.entity.documents)} for m in doc.mentions),
                        key=lambda e: (e["kind"], -e["count"])),
        same_file=[{"id": o.id, "filename": o.filename, "path": o.path} for o in lib.documents.values()
                   if o is not doc and o.sha256 == doc.sha256],
        copied_into=list(copies.values()),
        related=search.related(lib, doc))
    return out


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int):
    with store.Session() as s:
        return _detail(s.lib, _get_doc(s.lib, doc_id))


class DocumentPatch(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    doc_date: Optional[str] = None
    subject: Optional[str] = None
    matter: Optional[str] = None


@app.patch("/api/documents/{doc_id}")
def patch_document(doc_id: int, body: DocumentPatch):
    if ingest.running():
        raise HTTPException(409, "an ingest is running; try again when it has finished")
    with store.Session(write=True) as s:
        doc = _get_doc(s.lib, doc_id)
        changes = {k: (v.strip() or None) for k, v in body.model_dump(exclude_unset=True).items()
                   if k in EDITABLE and v is not None}
        for field, value in changes.items():
            setattr(doc, field, value)
        if changes:
            doc.edited = True
            s.lib.touch()
        return _detail(s.lib, doc)


@app.get("/api/documents/{doc_id}/pages/{page_no}/image")
def page_image(doc_id: int, page_no: int):
    with store.Session() as s:
        doc = _get_doc(s.lib, doc_id)
        if not 1 <= page_no <= doc.page_count:
            raise HTTPException(404, "page not found")
        rotation, sha, path = doc.pages[page_no - 1].rotation, doc.sha256, _source_path(doc)
    cache = config.PAGE_CACHE / f"{sha[:16]}_{page_no}_{rotation}.png"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(extract.render_page_png(path, page_no, rotation))
    return FileResponse(cache, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/documents/{doc_id}/file")
def source_file(doc_id: int):
    with store.Session() as s:
        doc = _get_doc(s.lib, doc_id)
        path, content_type, filename = _source_path(doc), doc.content_type, doc.filename
    return FileResponse(path, media_type=content_type, filename=filename, content_disposition_type="inline")


@app.get("/api/search")
def run_search(q: str = "", mode: str = "iac", limit: int = Query(25, ge=1, le=200)):
    if mode not in search.MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(search.MODES)}")
    return search.search(q, mode=mode, limit=limit)


class Feedback(BaseModel):
    query: str
    doc_id: int
    relevant: bool
    activation: Optional[float] = None


@app.post("/api/feedback")
def add_feedback(body: Feedback):
    """Record a relevance judgement; these calibrate the IAC match probabilities."""
    with store.Session(write=True) as s:
        doc = _get_doc(s.lib, body.doc_id)
        query = body.query.strip()
        s.lib.judgements[(query, doc.id)] = store.Judgement(query, doc, body.activation, body.relevant,
                                                            ingest.now())
        s.lib.touch()
        return {"judgements": len(s.lib.judgements)}


@app.get("/api/export.csv")
def export_csv():
    """Derived metadata next to what the migration workbook declared, one row per file."""
    columns = ["path", "filename", "page_count", "matter", "title", "doc_type", "doc_type_conf", "doc_date",
               "subject", "text_source", "ocr_conf", "sha256", "edited", "decl_matter", "decl_matter_title",
               "decl_reference", "decl_doc_type", "decl_comments"]
    kinds = ("person", "org", "case_no", "file_ref")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns + ["parties", "flags", "segments", "people", "organisations", "case_numbers",
                               "file_references"])
    with store.Session() as s:
        for doc in sorted(s.lib.documents.values(), key=lambda d: d.path):
            mentions = sorted(doc.mentions, key=lambda m: -m.count)
            writer.writerow(
                [getattr(doc, c) for c in columns]
                + ["; ".join(f"{name} ({role})" for name, role in doc.parties), "; ".join(doc.flags),
                   "; ".join(f"pp {g.start_page}-{g.end_page}: {g.doc_type or 'Unknown'}" for g in doc.segments)]
                + ["; ".join(m.entity.value for m in mentions if m.entity.kind == kind) for kind in kinds])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="agfilenet-metadata.csv"'})


# Serve the built React app, with client-side routes falling back to index.html.
if config.FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (config.FRONTEND_DIST / path).resolve()
        if path and config.FRONTEND_DIST in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(config.FRONTEND_DIST / "index.html")
