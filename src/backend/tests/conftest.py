import pymupdf
import pytest

from agfilenet import config, store

DOCS = {
    "LEG%2F1%2F1/writ.pdf": [
        "COMMONWEALTH OF THE BAHAMAS\nIN THE SUPREME COURT\nCommon Law and Equity Division\n2012/CLE/gen/00999\n"
        "BETWEEN\nANGELA THOMPSON\nPlaintiff\nAND\nTHE MINISTRY OF HEALTH\nDefendant\nWRIT OF SUMMONS\n"
        "Dated the 30th day of March, A.D., 2012. The Plaintiff claims damages for negligence after a fall "
        "on wet stairs at the clinic. Our reference 36/T/514.",
        "STATEMENT OF CLAIM\nThe Plaintiff Angela Thompson was at all material times a nurse employed at the "
        "clinic. Particulars of negligence: failing to keep the stairs dry.",
    ],
    "LEG%2F1%2F1/memo.pdf": [
        "MEMORANDUM\nOur Reference: 36/T/514\nDate: 4th January, 2021\nTo: Permanent Secretary\n"
        "Re: Angela Thompson v Ministry of Health\nPlease provide instructions on the injury sustained on the "
        "staircase so that a defence can be filed. Mr. Peter Rolle has conduct of this file.",
    ],
    "LEG%2F2%2F9/conveyance.pdf": [
        "CONVEYANCE\nTHIS CONVEYANCE is made the 6th day of June, 2007 between the Vendor and Monique Cox "
        "the Purchaser of a parcel of land comprising 317 square feet. Recorded in Volume 9999 at pages 460. "
        "Passport No. shown to the attorney. Mr. Peter Rolle witnessed the deed.",
    ],
}


def make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), text, fontsize=11)
    doc.save(path)
    doc.close()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A small data directory of text PDFs and an empty object database."""
    data, var = tmp_path / "data", tmp_path / "var"
    for rel, pages in DOCS.items():
        target = data / "pkg" / "documents" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        make_pdf(target, pages)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "VAR_DIR", var)
    monkeypatch.setattr(config, "DB_PATH", var / "test.fs")
    monkeypatch.setattr(config, "PAGE_CACHE", var / "pages")
    yield data
    store.close()
