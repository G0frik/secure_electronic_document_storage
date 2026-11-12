import random
import re

from research.corpus import synthetic_ids as sid

N = 500


def seeded(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 - reproducible fake data, not crypto


def test_rnokpp_checksum_and_1900_birth_part():
    rng = seeded(1)
    for _ in range(N):
        female = rng.random() < 0.5
        code = sid.rnokpp(rng, female)
        assert re.fullmatch(r"\d{10}", code)
        assert 1 <= int(code[:5]) <= 365
        assert int(code[9]) == sid.rnokpp_check_digit(code[:9])
        assert int(code[8]) % 2 == (0 if female else 1)


def test_rnokpp_check_digit_known_value():
    # Valid example from the python-stdnum docs (stdnum.ua.rntrc).
    assert sid.rnokpp_check_digit("175901377") == 6


def test_iban_is_valid_and_uses_fake_bank():
    rng = seeded(2)
    for _ in range(N):
        iban = sid.iban_ua(rng)
        assert len(iban) == 29 and iban.startswith("UA")
        assert iban[4:10] == sid.IBAN_BANK_CODE
        rearranged = iban[4:] + iban[:4]
        assert int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def test_iban_check_digits_known_value():
    # ISO 13616 example: GB82 WEST 1234 5698 7654 32
    assert sid.iban_check_digits("GB", "WEST12345698765432") == "82"


def test_cards_are_luhn_valid_test_numbers():
    assert all(sid.luhn_ok(n) for n in sid.TEST_CARDS)
    assert not sid.luhn_ok("4111111111111112")


def test_formats_match_the_service_recognizers():
    rng = seeded(3)
    p = sid.person(rng)
    assert re.fullmatch(r"\+380\s?00\s?\d{3}\s?\d{2}\s?\d{2}", p["phone"])
    assert re.fullmatch(r"[А-ЯҐЄІЇ]{2}\s?\d{6}", p["passport"])
    assert p["email"].rsplit("@", 1)[1] in sid.EMAIL_DOMAINS
    key_id, secret = sid.aws_key_pair(rng)
    assert re.fullmatch(r"AKIA[0-9A-Z]{16}", key_id) and "FAKE" in key_id
    assert len(secret) == 40


def test_same_seed_same_output():
    assert sid.person(seeded(7)) == sid.person(seeded(7))
