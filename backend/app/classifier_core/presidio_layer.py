"""Microsoft Presidio (NER + regex) tier prediction.

Lifted from classify_sensitivity.py v6 — includes the v6 fixes:
  - Non-Latin filter on PERSON/LOCATION/NRP (Cyrillic NER suppression)
  - Custom CREDENTIAL recognizer (keys, secrets, API tokens, PEM private keys)
  - Custom RNOKPP + UA_PASSPORT + UA_PHONE recognizers for Ukrainian docs
  - Personal-vs-corporate email split for the CONFIDENTIAL bundle rule
  - Removed PHONE+PERSON+LOCATION bundle (v6 fix #2)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.classifier_core.tiers import Tier

# Per-entity tier mapping.
ENTITY_TO_TIER: dict[str, Tier] = {
    "US_SSN": Tier.RESTRICTED,
    "CREDIT_CARD": Tier.RESTRICTED,
    "IBAN_CODE": Tier.RESTRICTED,
    "US_BANK_NUMBER": Tier.RESTRICTED,
    "US_PASSPORT": Tier.RESTRICTED,
    "US_DRIVER_LICENSE": Tier.RESTRICTED,
    "MEDICAL_LICENSE": Tier.RESTRICTED,
    "CRYPTO": Tier.RESTRICTED,
    "CREDENTIAL": Tier.RESTRICTED,
    "RNOKPP": Tier.RESTRICTED,
    "UA_PASSPORT": Tier.RESTRICTED,
    "UA_PHONE": Tier.CONFIDENTIAL,
    "EMAIL_ADDRESS": Tier.CONFIDENTIAL,
    "PHONE_NUMBER": Tier.CONFIDENTIAL,
    "PERSON": Tier.CONFIDENTIAL,
    "LOCATION": Tier.CONFIDENTIAL,
    "NRP": Tier.CONFIDENTIAL,
    "IP_ADDRESS": Tier.INTERNAL,
    "URL": Tier.INTERNAL,
    "DATE_TIME": Tier.PUBLIC,
}

RESTRICTED_ENTITIES = {e for e, t in ENTITY_TO_TIER.items() if t == Tier.RESTRICTED}

# Per-entity confidence floor.
PER_ENTITY_MIN_SCORE: dict[str, float] = {
    "US_SSN": 0.40,
    "CREDIT_CARD": 0.40,
    "IBAN_CODE": 0.40,
    "US_BANK_NUMBER": 0.50,
    "US_PASSPORT": 0.50,
    "US_DRIVER_LICENSE": 0.50,
    "MEDICAL_LICENSE": 0.40,
    "CRYPTO": 0.50,
    "CREDENTIAL": 0.50,
    "RNOKPP": 0.40,
    "UA_PASSPORT": 0.40,
    "UA_PHONE": 0.40,
    "EMAIL_ADDRESS": 0.50,
    "PHONE_NUMBER": 0.40,
    "PERSON": 0.70,
    "LOCATION": 0.70,
    "NRP": 0.70,
    "IP_ADDRESS": 0.50,
    "URL": 0.50,
    "UK_NHS": 1.10,
    "DATE_TIME": 1.10,
}

CORPORATE_EMAIL_LOCALPARTS = {
    "press", "media", "info", "contact", "support", "sales", "hello", "hi",
    "team", "admin", "administrator", "hr", "marketing", "office", "office-ops",
    "ops", "no-reply", "noreply", "donotreply", "webmaster", "postmaster",
    "abuse", "security", "legal", "privacy", "ir", "investor", "investors",
    "careers", "jobs", "billing", "help", "feedback", "enquiries", "inquiries",
}


def email_localpart_is_corporate(value: str) -> bool:
    local = value.split("@", 1)[0].lower().strip()
    return local in CORPORATE_EMAIL_LOCALPARTS


def build_analyzer():  # type: ignore[no-untyped-def]
    """Construct a Presidio AnalyzerEngine with the v6 custom recognizers."""
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

    analyzer = AnalyzerEngine()

    # Credentials / secrets
    cred_patterns = [
        Pattern(
            name="key_value_secret",
            regex=r"(?i)\b(password|passwd|pwd|secret|shared[_\s-]?secret|api[_\s-]?key|access[_\s-]?token|private[_\s-]?key)\b\s*[:=]\s*\S{6,}",
            score=0.85,
        ),
        Pattern(
            name="ipsec_shared_secret",
            regex=r"(?i)IPSEC[_\s-]?SHARED[_\s-]?SECRET\s*[:=]?\s*[0-9a-f\-]{16,}",
            score=0.95,
        ),
        Pattern(
            name="aws_access_key_id",
            regex=r"\bAKIA[0-9A-Z]{16}\b",
            score=0.90,
        ),
        Pattern(
            name="pem_private_key",
            regex=r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
            score=0.99,
        ),
    ]
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="CREDENTIAL",
            patterns=cred_patterns,
            context=["password", "secret", "credential", "key", "token", "vpn", "auth"],
        )
    )

    # Ukrainian RNOKPP (10 digits + context)
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="RNOKPP",
            patterns=[Pattern(name="rnokpp_10_digit", regex=r"\b\d{10}\b", score=0.10)],
            context=["рнокпп", "інн", "ідентифікаційний", "идентификационный", "ipn"],
            supported_language="en",
        )
    )

    # Ukrainian internal passport (2 Cyrillic letters + 6 digits)
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="UA_PASSPORT",
            patterns=[
                Pattern(
                    name="ua_passport_series_number",
                    regex=r"\b[А-ЯҐЄІЇ]{2}\s?\d{6}\b",
                    score=0.70,
                )
            ],
            context=["паспорт", "серія", "passport"],
            supported_language="en",
        )
    )

    # Ukrainian mobile phone (+380)
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="UA_PHONE",
            patterns=[
                Pattern(
                    name="ua_phone_plus380",
                    regex=r"\+380\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}",
                    score=0.80,
                )
            ],
            context=["телефон", "phone"],
            supported_language="en",
        )
    )

    return analyzer


def presidio_scan(analyzer, text: str) -> dict[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Return {entity_type: {count, max_score, samples, raw_values}}."""
    results = analyzer.analyze(text=text, language="en")
    summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "max_score": 0.0, "samples": [], "raw_values": []}
    )
    for r in results:
        info = summary[r.entity_type]
        info["count"] += 1
        info["max_score"] = max(info["max_score"], r.score)
        raw = text[r.start : r.end]
        info["raw_values"].append(raw)
        if len(info["samples"]) < 2:
            masked = raw if len(raw) <= 8 else raw[:2] + "*" * (len(raw) - 4) + raw[-2:]
            info["samples"].append(masked)
    return dict(summary)


def _is_predominantly_non_latin(s: str, threshold: float = 0.5) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if not ("a" <= c.lower() <= "z"))
    return (non_latin / len(letters)) > threshold


_NER_LANGUAGE_SENSITIVE = {"PERSON", "LOCATION", "NRP"}


def _filter_by_floor(entity_summary: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Apply per-entity confidence floors and drop NER hits on non-Latin text."""
    out: dict[str, dict[str, Any]] = {}
    for ent, info in entity_summary.items():
        floor = PER_ENTITY_MIN_SCORE.get(ent, 0.50)
        if info["max_score"] < floor:
            continue
        if ent in _NER_LANGUAGE_SENSITIVE:
            raw_values = info.get("raw_values", [])
            kept = [v for v in raw_values if not _is_predominantly_non_latin(v)]
            if not kept:
                continue
            info = dict(info)
            info["raw_values"] = kept
            info["count"] = len(kept)
            info["samples"] = info["samples"][: len(kept)]
        out[ent] = info
    return out


def presidio_tier(entity_summary: dict[str, dict[str, Any]]) -> Tier:
    """Combine filtered Presidio findings into a single tier."""
    filtered = _filter_by_floor(entity_summary)

    for ent in filtered:
        if ent in RESTRICTED_ENTITIES:
            return Tier.RESTRICTED

    n_person = filtered.get("PERSON", {}).get("count", 0)
    n_phone = filtered.get("PHONE_NUMBER", {}).get("count", 0) + filtered.get(
        "UA_PHONE", {}
    ).get("count", 0)

    personal_emails = 0
    if "EMAIL_ADDRESS" in filtered:
        for v in filtered["EMAIL_ADDRESS"].get("raw_values", []):
            if not email_localpart_is_corporate(v):
                personal_emails += 1

    if n_phone >= 1 and n_person >= 1:
        return Tier.CONFIDENTIAL
    if personal_emails >= 1 and n_person >= 1:
        return Tier.CONFIDENTIAL
    if n_phone >= 2:
        return Tier.CONFIDENTIAL
    if personal_emails >= 2:
        return Tier.CONFIDENTIAL

    return Tier.PUBLIC
