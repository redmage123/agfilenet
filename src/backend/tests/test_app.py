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


def test_database_listing_matches_what_is_stored(client):
    doc_id = by_name(client)["writ.pdf"]["id"]
    client.post("/api/feedback", json={"query": "thompson", "doc_id": doc_id, "relevant": False, "activation": 0.2})
    db = client.get("/api/database").json()
    assert db["counts"]["documents"] == len(db["documents"]) == 3
    assert db["counts"]["entities"] == len(db["entities"]) > 0
    assert db["counts"]["pages"] == 4 and db["counts"]["chunks"] > 0 and db["file"]["size"] > 0
    assert all(d["ingested_at"] and "pages" not in d for d in db["documents"])
    person = next(e for e in db["entities"] if e["value"] == "Angela Thompson")
    assert person["kind"] == "person" and person["documents"] == 2 and person["mentions"] >= 2
    assert db["judgements"] == [{"query": "thompson", "doc_id": doc_id, "document": db["judgements"][0]["document"],
                                 "relevant": False, "activation": 0.2, "created": db["judgements"][0]["created"]}]
    assert db["jobs"] == [] or db["jobs"][0]["status"] == "done"


def test_filter_counts_follow_the_other_filters(client):
    count = lambda facet, value: next(f["count"] for f in facet if f["value"] == value)
    everything = client.get("/api/facets").json()
    assert count(everything["doc_type"], "Conveyance") == 1 and count(everything["matter"], "LEG/1/1") == 2
    narrowed = client.get("/api/facets", params={"q": "thompson"}).json()
    assert count(narrowed["doc_type"], "Conveyance") == 0           # still offered, with nothing behind it
    assert count(narrowed["doc_type"], "Memorandum") == 1
    assert [f["value"] for f in narrowed["doc_type"]] == [f["value"] for f in everything["doc_type"]]
    chosen = client.get("/api/facets", params={"doc_type": "Memorandum"}).json()
    assert count(chosen["doc_type"], "Conveyance") == 1             # a menu does not count against itself
    assert count(chosen["matter"], "LEG/2/9") == 0 and count(chosen["flag"], "pii:passport") == 0
    for facet, value in (("doc_type", "Memorandum"), ("matter", "LEG/1/1"), ("flag", "bundle")):
        listed = client.get("/api/documents", params={"q": "thompson", facet: value}).json()
        assert len(listed) == count(narrowed[facet], value)


def test_iac_search_fans_out_to_words_of_similar_meaning(client):
    docs = by_name(client)
    data = client.get("/api/search", params={"q": "lawsuit", "mode": "iac"}).json()     # the word is in no file
    assert data["network"]["unknown_terms"] == ["lawsuit"]
    found = {e["term"] for e in data["network"]["expanded"]}
    assert found and found <= {"plaintiff", "claim", "defendant", "defence", "court", "summon"}
    assert all(e["from"] == "lawsuit" and 0.78 <= e["similarity"] < 1 for e in data["network"]["expanded"])
    top = data["results"][0]
    assert top["id"] == docs["writ.pdf"]["id"] and top["probability"] > 0.5
    assert not top["matched_text"] and "[[" in top["snippet"]      # shows the passage with the related word
    assert any("related to lawsuit" in w["label"] for w in top["why"])
    plain = client.get("/api/search", params={"q": "zebra spaceship", "mode": "iac"}).json()
    assert plain["network"]["expanded"] == []


# --- language processing -----------------------------------------------------
def test_words_are_reduced_to_their_dictionary_form(client):
    from agfilenet.textutil import tokens
    assert tokens("She was employed; they failed to keep the staircases dry") == \
        tokens("employing fails keeping staircase drier")[:4] + ["dry"]
    assert tokens("Thompson's Bahamas summonses") == ["thompson", "bahama", "summons"]   # names are left nearly alone
    docs = by_name(client)
    hits = client.get("/api/search", params={"q": "employs nurses", "mode": "keyword"}).json()["results"]
    assert [h["id"] for h in hits] == [docs["writ.pdf"]["id"]]      # the file says "a nurse employed"


def test_misread_words_are_found_under_the_intended_word():
    from agfilenet import spelling, store as st
    counts = {"negligence": 12, "negligcnce": 1, "neglgence": 2, "plaintiff": 9, "plaintifs": 1,
              "thompson": 8, "thonpson": 1, "clinic": 7, "clinics": 1}
    fixes = spelling.corrections(counts)
    assert fixes == {"negligcnce": "negligence", "neglgence": "negligence", "plaintifs": "plaintiff"}
    assert spelling.corrections({"planted": 6, "planned": 6, "planxed": 1, "plannned": 1}) == \
        {"plannned": "planned"}                                      # one edit from two words: left alone
    index = st.TextIndex(fixes)
    index.add(1, "particulars of negligcnce at the clinic")
    index.add(2, "a conveyance of land")
    assert set(index.search(["negligence"])[0]) == {1} and set(index.search(["negligcnce"])[0]) == {1}
    index.remove(1, "particulars of negligcnce at the clinic")
    assert not index.search(["negligence"])[0]


def test_spellings_of_one_name_become_one_entity():
    from agfilenet import entities

    def seen(count, *where):
        return {"count": count, "where": set(where)}
    names = {("person", "angela thompson"): seen(9, "m1"), ("person", "a thompson"): seen(2, "m1"),
             ("person", "angela thonpson"): seen(1, "m1"), ("person", "andrew thompson"): seen(3, "m2"),
             ("person", "p rolle"): seen(1, "m3"), ("person", "peter rolle"): seen(4, "m3"),
             ("person", "patricia rolle"): seen(4, "m3"), ("person", "john smith"): seen(2, "m1"),
             ("person", "joan smith"): seen(2, "m1"), ("org", "ministry of health"): seen(5, "m1"),
             ("org", "the ministry of health"): seen(2, "m7"), ("org", "ministry of heaith"): seen(1, "m1")}
    stored = entities.cluster(names)
    same = lambda a, b: stored[a] == stored[b]
    assert same(("person", "a thompson"), ("person", "angela thompson"))        # an initial, in the same matter
    assert same(("person", "angela thonpson"), ("person", "angela thompson"))   # a misreading
    assert stored[("person", "angela thompson")] == ("person", "angela thompson")
    assert not same(("person", "andrew thompson"), ("person", "angela thompson"))   # another matter, another name
    assert stored[("person", "p rolle")] == ("person", "p rolle")               # could be either Rolle: not guessed
    assert not same(("person", "john smith"), ("person", "joan smith"))         # two people, not a misreading
    assert len({stored[k] for k in names if k[0] == "org"}) == 1
    assert entities.clean("person", "Mr. PETER ROLLE") == "Peter Rolle"
    assert entities.clean("person", "Plaintiff") is None and entities.clean("org", "OF SUMMONS") is None


def test_a_name_read_in_one_file_is_linked_wherever_it_is_written():
    from agfilenet import ingest, store as st
    lib = st.Library()
    for name, text, names in [("a.pdf", "A note that Delroy Farquharson called.", [("person", "Delroy Farquharson", 0.99)]),
                              ("b.pdf", "Spoke again with delroy farquharson about the lease.", []),
                              ("c.pdf", "Nothing here about Farquharson Delroy Ltd.", [])]:
        doc = lib.add_document(name, name)
        doc.status = "ok"
        page = st.Page(doc, 1, text, "text")
        page.names = names
        doc.pages.append(page)
    ingest.analyse(lib)
    assert sorted(lib.entities[("person", "delroy farquharson")].documents) == [1, 2]


def test_names_are_found_without_a_title_in_front(client):
    from agfilenet import ner
    if not ner.available():
        pytest.skip("the name-finding model is not installed")
    found = ner.find("The affidavit was sworn by Monique Cox at Nassau before an officer of the Ministry of Health.")
    assert [(kind, text) for kind, text, _conf in found] == \
        [("person", "Monique Cox"), ("place", "Nassau"), ("org", "Ministry of Health")]
    db = client.get("/api/database").json()
    people = {e["value"]: e for e in db["entities"] if e["kind"] == "person"}
    assert people["Angela Thompson"]["documents"] == 2 and people["Peter Rolle"]["documents"] == 2
    assert not any("Plaintiff" in name or "Summons" in name for name in people)
    assert all("aliases" in e for e in db["entities"])


def test_files_get_a_summary_and_a_topic(client):
    docs = by_name(client)
    summary = docs["writ.pdf"]["summary"]
    assert "negligence" in summary and summary.startswith("The Plaintiff") and "STATEMENT OF CLAIM" not in summary
    assert all(d["topic"] for d in docs.values()) and len({d["topic"] for d in docs.values()}) == 2
    topics = client.get("/api/facets").json()["topic"]
    assert sum(t["count"] for t in topics) == 3
    listed = client.get("/api/documents", params={"topic": topics[0]["value"]}).json()
    assert len(listed) == topics[0]["count"]
    assert "topic" in client.get("/api/export.csv").text.splitlines()[0]


def test_type_suggestions_follow_the_types_of_similar_files():
    import numpy as np
    from types import SimpleNamespace
    from agfilenet import insight

    def doc(doc_type, edited=False, conf=0.9):
        return SimpleNamespace(doc_type=doc_type, edited=edited, doc_type_conf=conf, suggested_type=None,
                               suggested_conf=None)
    letter, memo = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    near = lambda v, w: (v + 0.05 * w) / np.linalg.norm(v + 0.05 * w)
    docs = [doc("Letter"), doc("Letter"), doc("Letter"), doc("Memorandum"), doc("Memorandum"), doc("Memorandum"),
            doc(None, conf=None), doc("Memorandum", conf=0.4), doc("Affidavit", edited=True)]
    vectors = np.array([letter, near(letter, memo), letter, memo, near(memo, letter), memo,
                        near(letter, memo), letter, np.array([0.8, 0.0, 0.6])])
    insight.suggest_types(docs, vectors, vectors.copy())
    assert docs[6].suggested_type == "Letter" and docs[6].suggested_conf >= 0.5     # untyped, sits among letters
    assert docs[7].suggested_type == "Letter"                                       # a weak rule is overruled
    assert docs[0].suggested_type is None and docs[3].suggested_type is None        # already agree
    assert docs[8].suggested_type is None                                           # a person decided: not second-guessed


def test_correcting_a_type_is_kept_as_an_example(client):
    doc_id = by_name(client)["memo.pdf"]["id"]
    patched = client.patch(f"/api/documents/{doc_id}", json={"doc_type": "Letter"}).json()
    assert patched["doc_type"] == "Letter" and patched["suggested_type"] is None
    assert {d["doc_type"] for d in by_name(client).values()} == {"Letter", "Writ of Summons", "Conveyance"}


def test_second_reading_reorders_the_best_results(client):
    from agfilenet import rerank
    if not rerank.available():
        pytest.skip("the re-ranking model is not installed")
    docs = by_name(client)
    data = client.get("/api/search", params={"q": "who fell on the stairs", "mode": "iac"}).json()
    top = data["results"][0]
    assert top["id"] == docs["writ.pdf"]["id"] and data["reread"] >= 1
    assert top["reread"] > 0.5 and top["probability"] >= top["first_probability"]
    assert [h["probability"] for h in data["results"]] == sorted((h["probability"] for h in data["results"]),
                                                                 reverse=True)
    plain = client.get("/api/search", params={"q": "who fell on the stairs", "mode": "iac", "reread": "false"}).json()
    assert plain["reread"] == 0 and all(h["reread"] is None for h in plain["results"])
    assert all(h["probability"] == h["first_probability"] for h in plain["results"])
    number = client.get("/api/search", params={"q": "36/T/514", "mode": "iac"}).json()
    assert number["reread"] == 0                                    # a reference is not a question to be read


def test_deeper_search_adds_other_wordings(client, monkeypatch):
    from agfilenet import llm
    asked = []
    monkeypatch.setattr(llm, "rewordings", lambda q, wait=30: asked.append(q) or ("sale of a plot of land",))
    docs = by_name(client)
    plain = client.get("/api/search", params={"q": "disposal of realty", "mode": "iac"}).json()
    deep = client.get("/api/search", params={"q": "disposal of realty", "mode": "iac", "deep": "true"}).json()
    assert asked == ["disposal of realty"] and plain["also"] == [] and deep["also"] == ["sale of a plot of land"]
    first = lambda data: {h["id"]: h["first_probability"] for h in data["results"]}
    conveyance = docs["conveyance.pdf"]["id"]
    assert first(deep)[conveyance] >= first(plain).get(conveyance, 0)
    assert deep["results"][0]["id"] == conveyance


def test_a_question_is_answered_from_the_passages_found(client, monkeypatch):
    import time
    from agfilenet import llm
    seen = {}

    def fake_answer(question, passages):
        seen.update(question=question, passages=passages)
        return "Peter Rolle has conduct of the file [1]."
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "answer", fake_answer)
    docs = by_name(client)
    asked = client.post("/api/ask", json={"question": " Who has conduct of the Thompson file? "}).json()
    assert asked["status"] == "thinking" and asked["question"] == "Who has conduct of the Thompson file?"
    assert asked["sources"][0]["id"] == docs["memo.pdf"]["id"] and asked["sources"][0]["page"] == 1
    assert "conduct of this file" in asked["sources"][0]["text"]
    for _ in range(50):
        state = client.get(f"/api/ask/{asked['id']}").json()
        if state["status"] != "thinking":
            break
        time.sleep(0.1)
    assert state == {"status": "done", "answer": "Peter Rolle has conduct of the file [1]."}
    assert seen["passages"] == [s["text"] for s in asked["sources"]]
    assert client.get("/api/ask/nonsense").status_code == 404
    assert client.post("/api/ask", json={"question": "  "}).status_code == 422
    monkeypatch.setattr(llm, "available", lambda: False)
    without = client.post("/api/ask", json={"question": "Who bought the land?"}).json()
    assert without["status"] == "unavailable" and without["sources"]    # the passages are still worth having


def test_status_says_which_models_are_installed(client):
    assert set(client.get("/api/status").json()["models"]) == {"names", "reread", "language"}


def test_an_older_database_is_brought_up_to_date(client):
    with store.Session(write=True) as s:
        assert not ingest.needs_upgrade(s.lib)
        s.lib.text_index.version = 1
        for doc in s.lib.documents.values():
            doc.summary = doc.summary_of = doc.topic = None
    with store.Session() as s:
        assert ingest.needs_upgrade(s.lib)
    ingest.upgrade()
    with store.Session() as s:
        assert not ingest.needs_upgrade(s.lib) and s.lib.text_index.version == store.TextIndex.TERMS
    docs = by_name(client)
    assert docs["writ.pdf"]["summary"] and docs["writ.pdf"]["topic"] and len(docs) == 3
    hits = client.get("/api/search", params={"q": "stairs negligence", "mode": "keyword"}).json()["results"]
    assert hits[0]["id"] == docs["writ.pdf"]["id"]
