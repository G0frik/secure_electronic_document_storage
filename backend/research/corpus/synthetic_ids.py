"""Fake identifiers for corpus documents: valid-looking, but none can belong to a real person.

- RNOKPP: correct check digit, birth-date part inside 1900 (days 1..365 since 1899-12-31).
- IBAN UA: valid mod-97 checksum, bank code 999999 (not an issued MFO).
- Cards: published payment-network test numbers (Luhn-valid, never issued).
- Phones: +380 00 … (operator code 00 is not allocated).
- Emails: RFC 2606 reserved domains (example.com/.net/.org).
- AWS-style keys carry FAKE in the key id.

Every generator takes a `random.Random` so a seed reproduces the corpus.
"""

from __future__ import annotations

import random
import string

RNOKPP_WEIGHTS = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
IBAN_BANK_CODE = "999999"
TEST_CARDS = (
    "4111111111111111",
    "4012888888881881",
    "5555555555554444",
    "5105105105105100",
    "4000056655665556",
)
UA_PASSPORT_LETTERS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШ"

# (uk, en) with KMU-2010 transliteration; surnames that do not change with gender.
FIRST_NAMES_M = [
    ("Андрій", "Andrii"),
    ("Олег", "Oleh"),
    ("Тарас", "Taras"),
    ("Богдан", "Bohdan"),
    ("Василь", "Vasyl"),
    ("Юрій", "Yurii"),
    ("Микола", "Mykola"),
    ("Остап", "Ostap"),
]
FIRST_NAMES_F = [
    ("Олена", "Olena"),
    ("Ірина", "Iryna"),
    ("Наталія", "Nataliia"),
    ("Оксана", "Oksana"),
    ("Галина", "Halyna"),
    ("Софія", "Sofiia"),
    ("Христина", "Khrystyna"),
    ("Мар'яна", "Mariana"),
]
SURNAMES = [
    ("Коваленко", "Kovalenko"),
    ("Шевчук", "Shevchuk"),
    ("Бондаренко", "Bondarenko"),
    ("Ткаченко", "Tkachenko"),
    ("Кравчук", "Kravchuk"),
    ("Олійник", "Oliinyk"),
    ("Мельник", "Melnyk"),
    ("Лисенко", "Lysenko"),
    ("Савченко", "Savchenko"),
    ("Руденко", "Rudenko"),
]
EMAIL_DOMAINS = ("example.com", "example.net", "example.org")


def rnokpp_check_digit(first9: str) -> int:
    return sum(w * int(d) for w, d in zip(RNOKPP_WEIGHTS, first9, strict=True)) % 11 % 10


def rnokpp(rng: random.Random, female: bool | None = None) -> str:
    if female is None:
        female = rng.random() < 0.5
    days = rng.randint(1, 365)  # 1900 is not a leap year
    serial = f"{rng.randint(0, 999):03d}"
    gender = rng.choice("02468" if female else "13579")
    first9 = f"{days:05d}{serial}{gender}"
    return first9 + str(rnokpp_check_digit(first9))


def ua_passport(rng: random.Random) -> str:
    return "".join(rng.choices(UA_PASSPORT_LETTERS, k=2)) + f" {rng.randint(0, 999_999):06d}"


def ua_phone(rng: random.Random) -> str:
    return f"+380 00 {rng.randint(0, 999):03d} {rng.randint(0, 99):02d} {rng.randint(0, 99):02d}"


def iban_check_digits(country: str, bban: str) -> str:
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{98 - int(digits) % 97:02d}"


def iban_ua(rng: random.Random) -> str:
    bban = IBAN_BANK_CODE + "".join(rng.choices(string.digits, k=19))
    return "UA" + iban_check_digits("UA", bban) + bban


def luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def card(rng: random.Random) -> dict[str, str]:
    return {
        "number": rng.choice(TEST_CARDS),
        "expiry": f"{rng.randint(1, 12):02d}/{rng.randint(27, 31)}",
        "cvv": f"{rng.randint(0, 999):03d}",
    }


def aws_key_pair(rng: random.Random) -> tuple[str, str]:
    key_id = "AKIAFAKE" + "".join(rng.choices(string.ascii_uppercase + string.digits, k=12))
    secret = "".join(rng.choices(string.ascii_letters + string.digits + "/+", k=40))
    return key_id, secret


def password(rng: random.Random, length: int = 16) -> str:
    return "".join(rng.choices(string.ascii_letters + string.digits + "!#%&*-_", k=length))


def person(rng: random.Random, female: bool | None = None) -> dict[str, str]:
    """Synthetic person in both languages, with matching identifiers."""
    if female is None:
        female = rng.random() < 0.5
    first = rng.choice(FIRST_NAMES_F if female else FIRST_NAMES_M)
    last = rng.choice(SURNAMES)
    return {
        "name_uk": f"{first[0]} {last[0]}",
        "name_en": f"{first[1]} {last[1]}",
        "email": f"{first[1].lower()}.{last[1].lower()}@{rng.choice(EMAIL_DOMAINS)}",
        "phone": ua_phone(rng),
        "rnokpp": rnokpp(rng, female),
        "passport": ua_passport(rng),
        "iban": iban_ua(rng),
    }
