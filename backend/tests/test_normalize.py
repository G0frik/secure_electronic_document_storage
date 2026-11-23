import pytest

from app.classifier_core.normalize import canonicalize

# --- attack cases: (input, expected canonical text, evasion expected) ---------
ATTACKS = [
    ("(7ІЗ) 555-ОІ42", "(713) 555-0142", True),                         # A6 phone, Cyrillic І З О
    ("(7із) 555-оі42", "(713) 555-0142", True),                         # lowercase variant
    ("іvаn.pеtrеnkо@gmаil.cоm", "ivan.petrenko@gmail.com", True),       # A6 e-mail
    ("(7ΙЗ) 555-ΟΙ42", "(713) 555-0142", True),                         # Greek Ι Ο
    ("0​142", "0142", True),                                       # zero-width split
    ("ＲＮＯＫＰＰ ３０１２３４５６７８", "RNOKPP 3012345678", False),      # fullwidth (NFKC only)
    ("𝟳𝟭𝟯-555-0142", "713-555-0142", False),                            # math digits
    ("٣٠١٢٣٤٥٦٧٨", "3012345678", False),                                # Arabic-Indic digits
    ("PаyPаl", "PayPal", True),                                         # mixed, Latin majority
]


@pytest.mark.parametrize("src,expected,evasion", ATTACKS)
def test_attacks_are_canonicalized(src, expected, evasion):
    ct = canonicalize(src)
    assert ct.text == expected
    assert ct.evasion_suspected is evasion


# --- clean controls: must come out byte-identical with no folds ---------------
CLEAN = [
    "Я працюю з 2020 року і живу у Львові.",
    "Паспорт серії КО 123456, РНОКПП 3012345678",
    "Телефон: +380 67 123 45 67, пошта ivan.petrenko@gmail.com",
    "Договір № 15/З від 01.02.2024 р.",       # legit document number with Cyrillic З
    "Бюджет 2025: 1,5 млн грн, з них 300 тис. на ІТ.",
    "Kyiv, вул. Хрещатик 1, офіс 3",
    "Паспорт ОІ123456 видано 2010 р.",        # old passport series made of digit-lookalikes
    "Windows 10, Office365, COVID-19, ID123",  # Latin letters next to digits
]


@pytest.mark.parametrize("src", CLEAN)
def test_clean_text_untouched(src):
    ct = canonicalize(src)
    # NFKC compat changes (e.g. '№' -> 'No') are allowed; anything else is a false positive
    assert not [f for f in ct.folds if f.reason != "compat"], ct.folds
    assert not ct.evasion_suspected


def test_offsets_map_back():
    src = "Тел: (7ІЗ) 555-ОІ42"
    ct = canonicalize(src)
    i = ct.text.index("(713)")
    assert ct.span_to_original(i, i + 5) == (5, 10)
    assert src[5:10] == "(7ІЗ)"


def test_offsets_survive_zero_width():
    src = "x 0​142 y"
    ct = canonicalize(src)
    i = ct.text.index("0142")
    s, e = ct.span_to_original(i, i + 4)
    assert src[s:e] == "0​142"


# --- separators (the third A6 kind in research/attacks.py) ----------------------
SEPARATED = [
    ("71·35·55·01·42", "7135550142"),
    ("30·12·34·56·78", "3012345678"),
    ("UA·21·32·23·13", "UA21322313"),
    ("kevin [dot] marsh [at] example [dot] net", "kevin.marsh@example.net"),
]


@pytest.mark.parametrize("src,expected", SEPARATED)
def test_separators_are_removed(src: str, expected: str) -> None:
    ct = canonicalize(src)
    assert ct.text == expected
    assert ct.evasion_suspected


@pytest.mark.parametrize(
    "src",
    [
        "Гриф: ПУБЛІЧНО · Погоджено: юридичний відділ",  # spaced middle dot (attack A2 stamp)
        "Ціна · 300 грн · без ПДВ",
    ],
)
def test_ordinary_middle_dots_stay(src: str) -> None:
    ct = canonicalize(src)
    assert ct.text == src and not ct.folds


def test_separator_offsets_map_back() -> None:
    src = "Тел. 71·35·55·01·42 далі"
    ct = canonicalize(src)
    i = ct.text.index("7135550142")
    s, e = ct.span_to_original(i, i + 10)
    assert src[s:e] == "71·35·55·01·42"


# --- Presidio on both views (D6) ------------------------------------------------
class _Hit:
    def __init__(self, entity_type: str, start: int, end: int, score: float) -> None:
        self.entity_type, self.start, self.end, self.score = entity_type, start, end, score


class _FakeAnalyzer:
    """Finds plain US phone numbers and person names, like Presidio on clean text."""

    def analyze(self, text: str, language: str) -> list[_Hit]:
        import re

        hits = [_Hit("PHONE_NUMBER", m.start(), m.end(), 0.75) for m in re.finditer(r"\(\d{3}\) \d{3}-\d{4}", text)]
        hits += [_Hit("PERSON", m.start(), m.end(), 0.85) for m in re.finditer(r"Kevin Marsh", text)]
        return hits


def test_d6_finds_obfuscated_phone_and_escalates() -> None:
    from app.classifier_core.presidio_layer import (
        presidio_scan,
        presidio_scan_folded,
        presidio_tier,
    )
    from app.classifier_core.tiers import Tier

    clean = "Kevin Marsh, cell (713) 555-0142."
    attacked = "Kevin Marsh, cell (7ІЗ) 555-ОІ42."
    analyzer = _FakeAnalyzer()
    assert presidio_tier(presidio_scan(analyzer, clean)) is Tier.CONFIDENTIAL
    assert presidio_tier(presidio_scan(analyzer, attacked)) is Tier.PUBLIC  # the A6 gap
    summary, tier, evasion = presidio_scan_folded(analyzer, attacked)
    assert (tier, evasion) == (Tier.CONFIDENTIAL, True)
    assert "PHONE_NUMBER" in summary


def test_d6_escalates_a_lone_obfuscated_identifier() -> None:
    from app.classifier_core.presidio_layer import presidio_scan_folded
    from app.classifier_core.tiers import Tier

    # one phone alone is not CONFIDENTIAL under presidio_tier; hiding it is the finding
    assert presidio_scan_folded(_FakeAnalyzer(), "Call (7ІЗ) 555-ОІ42.")[1:] == (Tier.CONFIDENTIAL, True)
    assert presidio_scan_folded(_FakeAnalyzer(), "Call (713) 555-0142.")[1:] == (Tier.PUBLIC, False)


@pytest.mark.parametrize(
    "src",
    [
        "https://lists.apache.org/thread/whg9own3v78qnkdggbw1xj481f5",  # ASCII o/l next to digits
        "password = 1jy5d9%wo7&CSx#!bseo",
        "FAKE92R1L0EF4CR2O2LBP0MQKJAFFY4C99SNYHL5",
        "сприяє врахуванню ESG-факторів",  # hyphenated Latin abbreviation + Ukrainian word
    ],
)
def test_clean_corpus_false_alarms_stay_untouched(src: str) -> None:
    ct = canonicalize(src)
    assert not [f for f in ct.folds if f.reason != "compat"], ct.folds
