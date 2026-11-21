from agfilenet.textutil import chunk_text, squash, stem, tokens, unglue


def test_squash_ignores_spacing_and_case():
    assert squash("WRIT OF\nSummons.") == squash("WRITOFSUMMONS") == "writofsummons"


def test_unglue_splits_run_together_headings():
    assert unglue("WRITOFSUMMONSANDCLAIM").lower() == "writ of summons and claim"
    assert unglue("short words stay") == "short words stay"


def test_tokens_drop_stopwords_and_stem_plurals():
    assert tokens("The mortgages of the Plaintiff's hospital") == ["mortgage", "plaintiff", "hospital"]
    assert stem("summons") == "summon" and stem("address") == "address"


def test_chunk_text_overlaps():
    words = " ".join(str(i) for i in range(400))
    chunks = chunk_text(words, size=160, overlap=40)
    assert len(chunks) == 3
    assert chunks[0].split()[-40:] == chunks[1].split()[:40]
    assert chunk_text("") == []
