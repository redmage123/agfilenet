"""Rule-based metadata extraction from page text.

Everything here is deterministic and local: document type per page, bundle
segmentation, dates, case and file references, parties, people,
organisations and sensitive-data flags.
"""
import re
from collections import Counter
from difflib import SequenceMatcher

from .textutil import norm_name, squash

# --- document types ---------------------------------------------------------
# (type, [(phrase in squashed form, weight), ...]). A phrase found in the head
# of a page counts triple and marks the page as the start of a document.
TYPE_RULES = [
    ("File Cover", [("filetitleornameofperson", 6), ("formom3", 3)]),
    ("Writ of Summons", [("writofsummons", 5), ("wecommandyou", 3)]),
    ("Statement of Claim", [("statementofclaim", 4), ("particularsofnegligence", 2)]),
    ("Notice of Appearance", [("noticeofappearance", 6), ("noticeofapprearance", 6),
                              ("takenoticethatanappearance", 3)]),
    ("Memorandum of Appearance", [("memorandumofappearance", 6), ("memorandumofapprearance", 6),
                                  ("pleaseenteranappearance", 4)]),
    ("Summons", [("summons", 2), ("letallpartiesconcerned", 4), ("admittedtobail", 2)]),
    ("Affidavit", [("affidavit", 3), ("makeoathandsay", 4), ("swornto", 2), ("swornat", 2)]),
    ("Minute Paper", [("minutepaper", 6)]),
    ("Memorandum", [("memorandum", 3), ("ourreference", 1), ("yourreference", 1)]),
    ("Email", [("subject", 1), ("bahamasgov", 2), ("sentby", 2), ("confidentialitynotice", 2)]),
    ("Fax Cover Sheet", [("facsimiletransmittal", 6), ("faxcoversheet", 6),
                         ("totalnoofpages", 3), ("liaisonofficer", 1)]),
    ("Letter", [("dearsir", 3), ("dearmadam", 3), ("dearmr", 3), ("dearms", 3),
                ("yourssincerely", 3), ("yoursfaithfully", 3), ("referenceismadeto", 2),
                ("abovecaptioned", 2), ("forandonbehalfof", 2), ("pleaseadvise", 2),
                ("enclosedherein", 2)]),
    ("Conveyance", [("conveyance", 3), ("vendor", 1), ("purchaser", 1)]),
    ("Mortgage", [("mortgage", 3), ("borrower", 1), ("lender", 1), ("mortgagor", 1)]),
    ("Deed of Assent", [("deedofassent", 6), ("realestatedevolution", 3)]),
    ("Deed of Assignment", [("deedofassignment", 6), ("assignor", 2), ("assignee", 2)]),
    ("Survey Plan", [("planshowing", 4), ("surveyedattheinstance", 5), ("scale1", 2)]),
    ("Appraisal Report", [("appraisalreport", 6), ("marketvalue", 2)]),
    ("Title Search", [("instrumentsearchresults", 6), ("instrumentdetails", 6), ("causelist", 2)]),
    ("Charge Sheet", [("natureofoffence", 5), ("chargesheet", 5), ("complainant", 2)]),
    ("Medical Certificate", [("medicalcertificate", 5), ("homeconfinement", 3),
                             ("internalmedicine", 2), ("admittedto", 1)]),
    ("Acknowledgement of Receipt", [("herebyacknowledgereceipt", 6), ("servedby", 2),
                                    ("receivedby", 1)]),
    ("Diplomatic Note", [("diplomaticnote", 6), ("embassyoftheunitedstates", 3)]),
    ("Proposal", [("proposalfor", 5), ("generalstatementoftheissue", 3)]),
    ("Submission", [("submission", 3), ("factualmatrix", 2), ("mitigation", 1)]),
    ("Questionnaire", [("questionnaire", 6)]),
    ("Acquisition Notice", [("declarationofintendedacquisition", 6), ("noticeofpossession", 6),
                            ("declarationofvesting", 6), ("acquisitionoflandact", 3)]),
    ("Identity Document", [("passport", 3), ("nationality", 1), ("dateofbirth", 1)]),
]
HEAD_LINES = 14
START_THRESHOLD = 9   # head weight x3 needed to call a page the start of a document
MIN_TYPE_SCORE = 4


def classify_page(text):
    """Return (type, confidence, is_start) for one page of text."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # A heading is in capitals, short, or opens its line; "we have been served with a
    # Writ of Summons" in the first paragraph of a letter is not one.
    head = [(squash(ln), sum(c.isupper() for c in ln) > 0.6 * sum(c.isalpha() for c in ln))
            for ln in lines[:HEAD_LINES]]
    body = squash(text)
    scores, head_scores = {}, {}
    for doc_type, rules in TYPE_RULES:
        total = head_total = 0
        for phrase, weight in rules:
            if any(phrase in ln and (caps or len(ln) <= len(phrase) + 12 or ln.find(phrase) <= 12)
                   for ln, caps in head):
                head_total += 3 * weight
            elif phrase in body:
                total += weight
        if total + head_total:
            scores[doc_type] = total + head_total
            head_scores[doc_type] = head_total
    # A specific appearance/deed heading outranks the generic word it contains.
    for specific, generic in (("Memorandum of Appearance", "Memorandum"),
                              ("Writ of Summons", "Summons"),
                              ("Deed of Assignment", "Conveyance")):
        if head_scores.get(specific, 0) >= START_THRESHOLD:
            scores.pop(generic, None)
    if not scores:
        return None, 0.0, False
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, top = ranked[0]
    if top < MIN_TYPE_SCORE:
        return None, 0.0, False
    second = ranked[1][1] if len(ranked) > 1 else 0
    return best, round(top / (top + second + 2), 3), head_scores.get(best, 0) >= START_THRESHOLD


def segment_pages(page_types):
    """Group pages into runs that look like separate documents within one file.

    page_types: list of (page_no, type, is_start, dup_of_first_in_segment_candidate).
    Returns [(start_page, end_page, type)].
    """
    segments = []
    for page_no, doc_type, is_start, repeats in page_types:
        new = not segments
        if segments and is_start and doc_type:
            current = segments[-1]
            new = doc_type != current[2] or repeats
        if new:
            segments.append([page_no, page_no, doc_type])
        else:
            segments[-1][1] = page_no
            if segments[-1][2] is None:
                segments[-1][2] = doc_type
    return [tuple(s) for s in segments]


# --- dates ------------------------------------------------------------------
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORD = r"(?:st|nd|rd|th|tn|[\"'’`][a-z]{1,2})?"   # OCR reads 9th as 9"h, 12'h or 29tn
_DATE_PATTERNS = [
    # 12th day of January, A.D., 2018  /  25th June, 2018  /  4 January 2021
    (re.compile(r"\b(\d{1,2})\s*" + _ORD + r"\.?\s*(?:day\s+of\s+)?" + _MON +
                r"\.?,?\s*(?:a\.?\s?d\.?,?\s*)?((?:19|20)\d{2})\b", re.I), "dmy"),
    # June 6th, 2007 / MAR 30 2012
    (re.compile(r"\b" + _MON + r"\.?\s+(\d{1,2})\s*" + _ORD + r",?\s*((?:19|20)\d{2})\b", re.I), "mdy"),
    # 30/03/2012, 2.5.2003 (day first, as used on these files)
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2})\b"), "num"),
]


def find_dates(text):
    """Return ISO dates found in text, in order of appearance."""
    found = []
    for pattern, kind in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                if kind == "dmy":
                    d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
                elif kind == "mdy":
                    mo, d, y = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
                else:
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if mo > 12 >= d:
                        d, mo = mo, d
            except (KeyError, ValueError):
                continue
            if 1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2030:
                found.append((m.start(), f"{y:04d}-{mo:02d}-{d:02d}"))
    return [iso for _pos, iso in sorted(found)]


# --- references -------------------------------------------------------------
_CASE_PATTERNS = [
    re.compile(r"\b((?:19|20)\d{2})\s*/?\s*CLE\s*/\s*gen\s*/\s*(?:FP\s*/\s*)?[O0-9]{3,6}", re.I),
    re.compile(r"\bCLE\s*/\s*gen\s*/\s*(?:FP\s*/\s*)?\d{3,6}(?:\s*/\s*|\s+of\s+)(?:19|20)\d{2}", re.I),
    re.compile(r"\bMCCrAPP\s*(?:No\.?:?)?\s*\d+\s+of\s+(?:19|20)\d{2}", re.I),
    re.compile(r"\b\d-\d{2}-\d{6}\b"),
    re.compile(r"\b(?:VBI|Info(?:rmation)?|Case)\s*(?:No\.?|#)\s*:?\s*\d{1,4}/\d{1,2}/(?:19|20)\d{2}", re.I),
    re.compile(r"\bMCR\s*\d+/(?:19|20)\d{2}", re.I),
]
_FILE_REF = re.compile(
    r"\b(?:LEG|OPM|MFA|MLLG|PHA|MOW&?U?)\s*/\s*[A-Z0-9&]{1,8}(?:\s*/\s*[A-Z0-9&]{1,8}){1,3}\b"
    r"|\b36\s*/\s*[A-Z]\s*/\s*\d{2,4}\b"
    r"|\bG\.O\.\s*\d+[A-Z]?\b", re.I)
_REGISTRY = re.compile(r"\bVOL(?:UME)?\.?\s*(\d{3,5})\s*,?\s*(?:AT\s+)?PAGES?\s*(\d{1,4})", re.I)
_BOOK = re.compile(r"\bbook\s+(\d{3,5})\s*,?\s*(?:at\s+)?pages?\s*(\d{1,4})", re.I)


def _clean_ref(text):
    return re.sub(r"\s*/\s*", "/", re.sub(r"\s+", " ", text)).strip()


def _clean_case(text):
    """One spelling for a case number however OCR read it: '2021 CLE/gen/0O770' -> '2021/CLE/gen/00770'."""
    ref = re.sub(r"(?<=[\d/])[Oo](?=\d)", "0", _clean_ref(text))
    return re.sub(r"^(\d{4}) (?=[A-Za-z])", r"\1/", ref)


def find_references(text):
    """Return {'case_no': [...], 'file_ref': [...], 'registry': [...]}."""
    cases = [_clean_case(m.group(0)) for p in _CASE_PATTERNS for m in p.finditer(text)]
    refs = [_clean_ref(m.group(0)).upper() for m in _FILE_REF.finditer(text)]
    vols = [f"Vol {m.group(1)}" for p in (_REGISTRY, _BOOK) for m in p.finditer(text)]
    return {"case_no": cases, "file_ref": refs, "registry": vols}


# --- parties, people, organisations ----------------------------------------
_PARTY_BLOCK = re.compile(
    r"BETWEEN\s+(?P<a>.{3,120}?)\s+(?P<ra>Plaintiff|Applicant|Appellant|Claimant)s?\b"
    r"\s+AND\s+(?P<b>.{3,160}?)\s+(?:(?:1st|2nd|3rd|First|Second|Third)\s+)?(?P<rb>Defendant|Respondent)s?\b", re.I | re.S)
_VERSUS = re.compile(r"\b(REGINA|R\.?|THE QUEEN)\s+(?:V\.?|VS\.?)\s+([A-Z][A-Za-z.'’ -]{3,40})")
_SUBJECT = re.compile(r"^\s*R[Ee]\s*[:;]\s*(.{6,200})$", re.M)
_TITLED = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Hon|Justice|Sir|Dame|Madam|Sgt|Inspector|Atty)\b\.?\s+"
    r"((?:[A-Z][A-Za-z'’-]+\.?\s+){0,3}[A-Z][A-Za-z'’-]{2,})")
_ORG_PATTERNS = [
    re.compile(r"\bMinistry of (?:[A-Z][A-Za-z]+|&|and|of|the)(?:[ \t]+(?:[A-Z][A-Za-z]+|&|and))*"),
    re.compile(r"\bOffice of [Tt]he (?:Attorney[- ]General|Prime Minister)", re.I),
    re.compile(r"\bPublic Hospitals? Authority", re.I),
    re.compile(r"\bRoyal Bahamas (?:Police|Defence) Force", re.I),
    re.compile(r"\bCommissioner of Police", re.I),
    re.compile(r"\b(?:Supreme Court|Court of Appeal|Magistrate'?s?'? Court)", re.I),
    re.compile(r"\bRegistrar General", re.I),
    re.compile(r"\b(?:[A-Z][A-Za-z.'’]+,?[ \t]+){1,4}(?:&\s+Co\b\.?|&\s+Associates|Law Chambers|"
               r"Bank(?:\s+(?:Limited|Ltd|PLC))?\b|Insurance Company\b|(?:Bahamas\s+)?Limited\b)"),
]
_NAME_STOP = {"dear", "the", "and", "for", "re", "attention", "street", "nassau", "bahamas", "between",
              "plaintiff", "defendant", "respondent", "applicant", "your", "our", "date", "director", "from",
              "to", "of", "in", "at", "on", "is", "was", "has", "who", "attorney", "counsel", "minister",
              "permanent", "secretary", "chief", "acting", "tel", "fax", "email", "po", "box", "with", "by",
              "now", "governor", "general", "office", "title", "there", "document", "meeting", "ref"}
_PLACE_WORDS = {"highway", "ext", "extension", "building", "road", "drive", "avenue"}  # named after people
_ORG_TAIL = {"our", "your", "date", "nassau", "east", "west", "meeting", "ihereby", "john", "ref", "and", "&"}
_STAMP_LINE = re.compile(r"c[co]urt|nassau|registry|^\W*" + _MON + r"\b[\s\d,.]*$|^[\W\d]*$", re.I)
_BOILERPLATE = ("commonwealthofthebaham", "inthesupremecourt", "inthecourtofappeal", "inthemagistrate",
                "commonlaw", "criminaldivision", "bahamas", "between", "page", "filetitle")


def _tidy(name):
    name = re.sub(r"\s+", " ", name).strip(" ,.;:-–")
    return name.title() if name.isupper() else name


def find_parties(text):
    """Return [(name, role)] from a court heading or an 'R v X' line."""
    parties = []
    m = _PARTY_BLOCK.search(text)
    if m:
        for name, role in ((m.group("a"), m.group("ra")), (m.group("b"), m.group("rb"))):
            # a court's received-stamp is often printed across the heading
            name = "\n".join(ln for ln in name.splitlines() if not _STAMP_LINE.search(ln))
            for part in re.split(r"\s+AND\s+", name):
                part = _tidy(re.sub(r"\b(?:1st|2nd|First|Second)\b.*$", "", part, flags=re.I | re.S))
                if 2 < len(part) < 80:
                    parties.append((part, role.title()))
    else:
        m = _VERSUS.search(text)
        if m:
            parties = [("Regina", "Prosecution"), (_tidy(m.group(2).split("\n")[0]), "Defendant")]
    return parties


def find_subject(text):
    m = _SUBJECT.search(text)
    return _tidy(m.group(1)) if m else None


def find_people(text):
    people = []
    for m in _TITLED.finditer(text):
        words, place = [], False
        for word in _tidy(m.group(1)).split():
            word = re.sub(r"['’]s$", "", word)
            key = word.lower().strip(".")
            if key in _NAME_STOP or key in _PLACE_WORDS:
                place = key in _PLACE_WORDS
                break  # the name ran into the next line of a letterhead or form
            words.append(word)
        if 2 <= len(words) <= 4 and not place:
            people.append(" ".join(words).rstrip(".,"))
    return people


def find_orgs(text):
    orgs = []
    for pattern in _ORG_PATTERNS:
        for m in pattern.finditer(text):
            words = _tidy(m.group(0)).split()
            while words and words[-1].lower() in _ORG_TAIL:
                words.pop()
            name = " ".join(words)
            if 4 < len(name) < 70 and len(words) > 1:
                orgs.append(name)
    return orgs


# --- sensitive data ---------------------------------------------------------
_PII_RULES = [
    ("pii:passport", re.compile(r"passport", re.I)),
    ("pii:national-insurance", re.compile(r"national\s+insurance\s*(?:#|no|number)", re.I)),
    ("pii:date-of-birth", re.compile(r"date\s+of\s+birth|\bD\.?O\.?B\b|\bborn\s+on\b|was\s+born", re.I)),
    ("sensitive:medical", re.compile(
        r"medical (?:history|condition|illness|note|certificate)|diagnos|hospital admission|"
        r"admitted to .{0,30}hospital|surgery|pneumothorax", re.I)),
]


def find_flags(text):
    return [flag for flag, pattern in _PII_RULES if pattern.search(text)]


# --- document-level summary -------------------------------------------------
def build_title(doc_type, parties, subject, first_text, doc_date):
    label = doc_type or "Document"
    if parties:
        names = [p[0] for p in parties]
        return f"{label}: {names[0]} v {' and '.join(names[1:])}" if len(names) > 1 else f"{label}: {names[0]}"
    if subject:
        return f"{label}: {subject[:110]}"
    for line in first_text.splitlines():
        line = line.strip()
        if len(line) > 12 and sum(c.isalpha() for c in line) > 0.6 * len(line) \
                and not squash(line).startswith(_BOILERPLATE) and squash(line) != squash(label):
            return f"{label}: {line[:90]}"
    return f"{label} ({doc_date})" if doc_date else label


_BIRTH = re.compile(r"\b(?:born|birth|d\.?o\.?b)\b[^\n]{0,40}", re.I)
_DATED = re.compile(r"\bDate[d:]?[^\n]{0,60}", re.I)


def pick_date(text):
    """The date the document gives for itself: a 'Dated ...' line if there is one,
    otherwise the first date that is not somebody's date of birth."""
    text = _BIRTH.sub(" ", text)
    for m in _DATED.finditer(text):
        dates = find_dates(m.group(0))
        if dates:
            return dates[0]
    dates = find_dates(text)
    return dates[0] if dates else None


def known_name(name, known):
    """The spelling of `name` from a list of known names, if OCR's version is close enough."""
    key = squash(name)
    for candidate in known:
        other = squash(candidate)
        if key == other or (len(other) > 8 and (other in key or
                                                SequenceMatcher(None, key, other).ratio() >= 0.85)):
            return candidate
    return name


def extract_document(pages, known_names=()):
    """Derive document metadata from [{page_no, text, page_type, is_start}].

    known_names: party names declared for the matter, used to repair OCR spellings.

    Returns a dict with doc_type, doc_type_conf, doc_date, subject, title, flags and
    entities = [(kind, value, page_no)].
    """
    full = "\n".join(p["text"] or "" for p in pages)
    first = pages[0]["text"] or "" if pages else ""
    entities, parties, subject = [], [], None
    for p in pages:
        text = p["text"] or ""
        refs = find_references(text)
        for kind, values in refs.items():
            entities += [(kind, v, p["page_no"]) for v in values]
        entities += [("person", v, p["page_no"]) for v in find_people(text)]
        entities += [("org", v, p["page_no"]) for v in find_orgs(text)]
        if not parties:
            parties = [(known_name(name, known_names), role) for name, role in find_parties(text)]
            entities += [("party", name, p["page_no"]) for name, _role in parties]
        subject = subject or find_subject(text)

    type_votes = Counter()
    for p in pages:
        if p.get("page_type"):
            type_votes[p["page_type"]] += 3 if p.get("is_start") else 1
    lead = next((p for p in pages if p.get("page_type") and p.get("is_start")), None)
    doc_type = lead["page_type"] if lead else (type_votes.most_common(1)[0][0] if type_votes else None)
    conf = round(type_votes[doc_type] / sum(type_votes.values()), 3) if doc_type else 0.0

    doc_date = pick_date(first) or pick_date(full)
    flags = find_flags(full)
    title = build_title(doc_type, parties, subject, first, doc_date)
    return {"doc_type": doc_type, "doc_type_conf": conf, "doc_date": doc_date, "subject": subject,
            "title": title, "flags": flags, "entities": entities, "parties": parties}


def entity_key(kind, value):
    return norm_name(value)
