from agfilenet import metadata

WRIT = """COMMONWEALTH OF THE BAHAMAS
IN THE SUPREME COURT
2012/CLE/gen/00999
BETWEEN
ANGELA THOMPSON
Plaintiff
AND
THE MINISTRY OF HEALTH
Defendant
WRITOFSUMMONS
Dated the 30th day of March, A.D., 2012"""


def test_classify_heading_despite_lost_spaces():
    doc_type, conf, is_start = metadata.classify_page(WRIT)
    assert doc_type == "Writ of Summons" and is_start and conf > 0.5


def test_classify_unknown_page():
    assert metadata.classify_page("lorem ipsum dolor sit amet") == (None, 0.0, False)


def test_specific_heading_beats_generic_word():
    page = "MEMORANDUM OF APPEARANCE\nPlease enter an appearance for the Defendant"
    assert metadata.classify_page(page)[0] == "Memorandum of Appearance"


def test_dates_in_several_styles():
    assert metadata.find_dates("the 30th day of March, A.D., 2012") == ["2012-03-30"]
    assert metadata.find_dates("June 6th, 2007 and 4 January 2021") == ["2007-06-06", "2021-01-04"]
    assert metadata.find_dates("received 25/06/2018") == ["2018-06-25"]
    assert metadata.find_dates("page 31/13/2018") == []


def test_references():
    refs = metadata.find_references("Action 2012/CLE/gen/00999, our ref LEG/555/1 and 36/T/514; Vol. 9999 pages 460")
    assert refs["case_no"] == ["2012/CLE/gen/00999"]
    assert set(refs["file_ref"]) == {"LEG/555/1", "36/T/514"}
    assert refs["registry"] == ["Vol 9999"]


def test_parties_from_court_heading():
    assert metadata.find_parties(WRIT) == [("Angela Thompson", "Plaintiff"), ("The Ministry Of Health", "Defendant")]


def test_people_and_flags():
    text = "Mr. Peter Rolle produced his passport. Date of Birth: 1 May 1970. National Insurance No. 123"
    assert metadata.find_people(text) == ["Peter Rolle"]
    assert set(metadata.find_flags(text)) == {"pii:passport", "pii:date-of-birth", "pii:national-insurance"}


def test_segment_pages_splits_bundle():
    pages = [(1, "Letter", True, False), (2, None, False, False), (3, "Writ of Summons", True, False),
             (4, "Statement of Claim", False, False), (5, "Writ of Summons", True, True)]
    assert metadata.segment_pages(pages) == [(1, 2, "Letter"), (3, 4, "Writ of Summons"), (5, 5, "Writ of Summons")]


def test_case_number_spelling_is_unified():
    refs = metadata.find_references("Action 2021 CLE/gen/0O770 and 2021/CLE/gen/00770")
    assert set(refs["case_no"]) == {"2021/CLE/gen/00770"}


def test_document_date_skips_dates_of_birth():
    assert metadata.pick_date("He was born on 2nd June, 1994 in Nassau.\nSworn the 3rd day of May, 2017") == "2017-05-03"
    assert metadata.pick_date("Received 1 March 2020.\nDated the 5th day of April, 2020") == "2020-04-05"
    assert metadata.pick_date("no dates here") is None


def test_ordinals_as_ocr_reads_them():
    assert metadata.find_dates('G.O.72A 9"h June, 2017') == ["2017-06-09"]
    assert metadata.find_dates("Dated the 29tn day of March, 2012") == ["2012-03-29"]


def test_court_stamp_is_not_part_of_a_party_name():
    heading = ("IN THE SUPREME COURT\nBETWEEN SUPREME COURT\nJAN 08 2018\nDARIANGREENE\nNassau, Bahamas\n"
               "Applicant\nAND\nTHE ATTORNEY GENERAL\nRespondent\nSUMMONS")
    assert metadata.find_parties(heading) == [("Dariangreene", "Applicant"), ("The Attorney General", "Respondent")]
    meta = metadata.extract_document([{"page_no": 1, "text": heading}], ["Darian Greene", "The Attorney General"])
    assert meta["parties"][0] == ("Darian Greene", "Applicant")


def test_known_name_repairs_ocr_spelling_only_when_close():
    known = ["Marcello Lucas Carter", "The Ministry of Health"]
    assert metadata.known_name("Marc Ello Lucas Carter", known) == "Marcello Lucas Carter"
    assert metadata.known_name("Theministry Ofhealth", known) == "The Ministry of Health"
    assert metadata.known_name("Peter Rolle", known) == "Peter Rolle"


def test_document_named_in_a_sentence_is_not_a_heading():
    letter = ("Commissioner of Police\n25th June, 2018\nRE: SMITH AND COMMISSIONER OF POLICE\n"
              "Reference is made to the above captioned action.\n"
              "We have been served with a Writ of Summons by the Plaintiff in the above captioned\naction.\n"
              "David Whyms\n(for and on behalf of) Director of Legal Affairs")
    assert metadata.classify_page(letter)[0] == "Letter"


def test_roads_named_after_people_are_not_people():
    people = metadata.find_people("Sir Milo Butler Highway and Mr. Daniel Whitfield. Now the")
    assert people == ["Daniel Whitfield"]
