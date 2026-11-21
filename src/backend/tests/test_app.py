"""End-to-end: ingest a small folder into the object database, then use the API."""
import pytest
from fastapi.testclient import TestClient

from agfilenet import ingest, store
from agfilenet.api import app


@pytest.fixture
def client(workspace):
    ingest.run()
    return TestClient(app)


def by_name(client):
    return {d["filename"]: d for d in client.get("/api/documents").json()}


def test_ingest_builds_metadata(client):
    docs = by_name(client)
    assert set(docs) == {"writ.pdf", "memo.pdf", "conveyance.pdf"}
    writ = docs["writ.pdf"]
    assert writ["doc_type"] == "Writ of Summons"
    assert writ["doc_date"] == "2012-03-30"
    assert writ["matter"] == "LEG/1/1"            # URL-encoded folder name decoded
    assert writ["title"].startswith("Writ of Summons: Angela Thompson v")
    assert "bundle" in writ["flags"]              # writ + statement of claim in one file
    assert docs["memo.pdf"]["doc_type"] == "Memorandum"
    assert docs["memo.pdf"]["doc_date"] == "2021-01-04"
    assert docs["conveyance.pdf"]["doc_type"] == "Conveyance"
    assert "pii:passport" in docs["conveyance.pdf"]["flags"]


def test_objects_reference_each_other(client):
    with store.Session() as s:
        writ = s.lib.by_path["pkg/documents/LEG%2F1%2F1/writ.pdf"]
        assert [p.page_no for p in writ.pages] == [1, 2] and writ.pages[0].document is writ
        assert [(g.start_page, g.doc_type) for g in writ.segments] == [(1, "Writ of Summons"), (2, "Statement of Claim")]
        ref = s.lib.entities[("file_ref", "36/t/514")]
        assert {d.filename for d in ref.documents.values()} == {"writ.pdf", "memo.pdf"}
        assert any(m.entity is ref for m in writ.mentions)
        assert all(c.document is writ for c in writ.chunks) and len(writ.chunks) == 2


def test_document_detail_and_related(client):
    docs = by_name(client)
    detail = client.get(f"/api/documents/{docs['memo.pdf']['id']}").json()
    assert {e["value"] for e in detail["entities"] if e["kind"] == "file_ref"} == {"36/T/514"}
    assert docs["writ.pdf"]["id"] in [r["id"] for r in detail["related"]]
    image = client.get(f"/api/documents/{docs['memo.pdf']['id']}/pages/1/image")
    assert image.status_code == 200 and image.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{docs['memo.pdf']['id']}/pages/9/image").status_code == 404
    assert client.get("/api/documents/999").status_code == 404


def test_keyword_search_and_phrases(client):
    docs = by_name(client)
    hits = client.get("/api/search", params={"q": "stairs negligence", "mode": "keyword"}).json()["results"]
    assert hits[0]["id"] == docs["writ.pdf"]["id"]
    assert "[[" in hits[0]["snippet"] and 0 < hits[0]["probability"] <= 1
    none = client.get("/api/search", params={"q": "zebra spaceship", "mode": "keyword"}).json()
    assert none["results"] == [] and none["p_none"] == 1.0
    phrase = client.get("/api/search", params={"q": '"square feet"', "mode": "keyword"}).json()["results"]
    assert [h["id"] for h in phrase] == [docs["conveyance.pdf"]["id"]]
    assert client.get("/api/search", params={"q": '"feet square"', "mode": "keyword"}).json()["results"] == []


def test_semantic_search_finds_meaning_without_the_words(client):
    docs = by_name(client)
    hits = client.get("/api/search", params={"q": "sale of real estate property", "mode": "semantic"}).json()["results"]
    assert hits and hits[0]["id"] == docs["conveyance.pdf"]["id"]


def test_iac_search_ranks_and_gives_probabilities(client):
    docs = by_name(client)
    data = client.get("/api/search", params={"q": "Angela Thompson", "mode": "iac"}).json()
    ids = [h["id"] for h in data["results"]]
    assert set(ids[:2]) == {docs["writ.pdf"]["id"], docs["memo.pdf"]["id"]}
    probabilities = {h["id"]: h["probability"] for h in data["results"]}
    assert probabilities[docs["writ.pdf"]["id"]] > 0.5
    assert probabilities.get(docs["conveyance.pdf"]["id"], 0) < probabilities[docs["memo.pdf"]["id"]]
    assert abs(sum(h["share"] for h in data["results"]) + data["p_none"] - 1) < 0.02
    assert data["network"]["settled"]
    assert any(w["label"] == "Angela Thompson" for w in data["results"][0]["why"])


def test_iac_quoted_reference_finds_its_file(client):
    docs = by_name(client)
    data = client.get("/api/search", params={"q": "2012/CLE/gen/00999", "mode": "iac"}).json()
    top = data["results"][0]
    assert top["id"] == docs["writ.pdf"]["id"] and top["probability"] > 0.5
    assert top["why"][0]["label"] == "2012/CLE/gen/00999"
    assert all(w["kind"] != "semantic" for w in top["why"])  # a number has no meaning to match


def test_iac_nonsense_query_matches_nothing(client):
    data = client.get("/api/search", params={"q": "zebra spaceship", "mode": "iac"}).json()
    assert all(h["probability"] < 0.5 for h in data["results"])
    assert client.get("/api/search", params={"q": "x", "mode": "bogus"}).status_code == 400


def test_manual_correction_survives_reanalysis(client):
    doc_id = by_name(client)["memo.pdf"]["id"]
    patched = client.patch(f"/api/documents/{doc_id}", json={"title": "Instructions memo", "doc_type": "Letter"}).json()
    assert patched["title"] == "Instructions memo" and patched["edited"]
    ingest.run()
    again = client.get(f"/api/documents/{doc_id}").json()
    assert again["title"] == "Instructions memo" and again["doc_type"] == "Letter"
    hits = client.get("/api/search", params={"q": "instructions memo", "mode": "iac"}).json()["results"]
    assert hits[0]["id"] == doc_id


def test_correction_refuses_a_date_that_is_not_a_date(client):
    doc_id = client.get("/api/documents").json()[0]["id"]
    for bad in ("next tuesday", "2021-02-30", "04/01/2021"):
        assert client.patch(f"/api/documents/{doc_id}", json={"doc_date": bad}).status_code == 422
    assert not client.get(f"/api/documents/{doc_id}").json()["edited"]
    assert client.patch(f"/api/documents/{doc_id}", json={"doc_date": " 2021-01-04 "}).json()["doc_date"] == "2021-01-04"


def test_reingest_is_incremental_and_drops_deleted_files(client, workspace):
    with store.Session() as s:
        before = {d.filename: d.ingested_at for d in s.lib.documents.values()}
        chunks = len(s.lib.chunks)
    (workspace / "pkg" / "documents" / "LEG%2F2%2F9" / "conveyance.pdf").unlink()
    ingest.run()
    with store.Session() as s:
        assert {d.filename: d.ingested_at for d in s.lib.documents.values()} == \
            {k: v for k, v in before.items() if k != "conveyance.pdf"}
        assert len(s.lib.chunks) == chunks - 1
        assert not s.lib.text_index.search(["conveyance"])[0]


def test_feedback_export_status(client):
    doc_id = by_name(client)["writ.pdf"]["id"]
    r = client.post("/api/feedback", json={"query": "thompson", "doc_id": doc_id, "relevant": True, "activation": 0.7})
    assert r.json() == {"judgements": 1}
    csv_text = client.get("/api/export.csv").text
    assert "writ.pdf" in csv_text and "Angela Thompson (Plaintiff)" in csv_text
    status = client.get("/api/status").json()
    assert status["counts"]["documents"] == 3 and status["counts"]["pages"] == 4
    assert status["job"] is None
    facets = client.get("/api/facets").json()
    assert {"value": "LEG/1/1", "count": 2} in facets["matter"]
    filtered = client.get("/api/documents", params={"flag": "pii:passport"}).json()
    assert [d["filename"] for d in filtered] == ["conveyance.pdf"]
