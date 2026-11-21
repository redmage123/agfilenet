"""Read the declared metadata out of the migration workbooks shipped with the files."""
import re

import openpyxl


def _key(header):
    return re.sub(r"[^a-z0-9]", "", str(header or "").lower())


def _rows(sheet):
    rows = sheet.iter_rows(values_only=True)
    try:
        headers = [_key(h) for h in next(rows)]
    except StopIteration:
        return
    for row in rows:
        record = {h: v for h, v in zip(headers, row) if h and v not in (None, "")}
        if record:
            yield record


def read_workbook(path):
    """Return {'matters': {number: {...}}, 'documents': {filename: {...}}}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    matters, documents = {}, {}
    if "Matters" in wb.sheetnames:
        for r in _rows(wb["Matters"]):
            number = str(r.get("matterfilenumber", "")).strip()
            if number:
                matters[number] = {"title": r.get("mattertitle"), "parties": [],
                                   "reference": str(r["referencenumber"]) if "referencenumber" in r else None}
    if "Matter Parties" in wb.sheetnames:
        for r in _rows(wb["Matter Parties"]):
            number = str(r.get("matterfilenumber", "")).strip()
            if number in matters and r.get("name"):
                matters[number]["parties"].append(str(r["name"]).strip())
    if "Matter Documents" in wb.sheetnames:
        for r in _rows(wb["Matter Documents"]):
            name = str(r.get("name", "")).strip()
            if name:
                documents[name] = {"matter": str(r.get("matterfilenumber", "")).strip() or None,
                                   "doc_type": r.get("documenttype"), "comments": r.get("comments")}
    wb.close()
    return {"matters": matters, "documents": documents}
