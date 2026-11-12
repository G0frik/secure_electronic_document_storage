from research.corpus.translate import protect, restore, units


def test_identifiers_are_protected_and_restored():
    text = (
        "access key id: AKIAFAKEG4NWACEBBDKK\npassword: w707%kPXDXQejbWLPa%0\n"
        "IBAN UA779999995395945716643474793, РНОКПП 0013550440, паспорт РР 366489, "
        "call +380 00 734 51 18 or (713) 555-0142, mail kevin.marsh@example.net & co <ok>"
    )
    xml = protect(text)
    for secret in (
        "AKIAFAKEG4NWACEBBDKK",
        "w707%kPXDXQejbWLPa%0",
        "UA779999995395945716643474793",
        "0013550440",
        "РР 366489",
        "+380 00 734 51 18",
        "(713) 555-0142",
        "kevin.marsh@example.net",
    ):
        assert f"<keep>{secret}</keep>" in xml
    assert "&amp; co &lt;ok&gt;" in xml
    assert restore(xml) == text


def test_config_lines_are_kept_and_comments_translated():
    segs = units("# Cache settings\nREDIS_URL=redis://:pw@cache:6379/0\n")
    assert ("Cache settings", True) in segs
    assert ("REDIS_URL=redis://:pw@cache:6379/0", False) in segs


def test_prose_is_split_into_paragraphs():
    assert units("a\n\nb") == [("a", True), ("b", True)]


def test_long_words_after_colon_are_translated():
    assert "<keep>" not in protect("PROCEDURE: Hemithyroidectomy")
