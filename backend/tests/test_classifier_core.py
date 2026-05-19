"""Unit tests for app.classifier_core (light-weight pieces).

The HuggingFace model is NOT loaded here — we only test the deterministic
helpers (tiers, threshold logic, email parsing, NER filter). End-to-end
classification with real models is exercised manually via the CLI and the
smoke test in the Phase 4 verification step.
"""

from __future__ import annotations

import pytest

from app.classifier_core.presidio_layer import (
    _filter_by_floor,
    _is_predominantly_non_latin,
    email_localpart_is_corporate,
    presidio_tier,
)
from app.classifier_core.tiers import Tier, max_tier, tier_rank
from app.classifier_core.zero_shot import CATEGORY_TO_TIER, short_name, zero_shot_tier


def test_max_tier_picks_highest() -> None:
    assert max_tier(Tier.PUBLIC, Tier.RESTRICTED) == Tier.RESTRICTED
    assert max_tier("internal", "confidential") == Tier.CONFIDENTIAL
    assert max_tier(Tier.PUBLIC) == Tier.PUBLIC
    assert max_tier() == Tier.PUBLIC


def test_tier_rank_string_or_enum() -> None:
    assert tier_rank(Tier.RESTRICTED) == 3
    assert tier_rank("public") == 0


# --- Zero-shot threshold logic ---


def test_zero_shot_tier_no_triggers_is_public() -> None:
    scores = {cat: 0.1 for cat in CATEGORY_TO_TIER}
    tier, triggered = zero_shot_tier(scores)
    assert tier == Tier.PUBLIC
    assert triggered == []


def test_zero_shot_tier_picks_highest_above_floor() -> None:
    # Find one restricted and one internal category to score.
    restricted_cat = next(c for c, t in CATEGORY_TO_TIER.items() if t == Tier.RESTRICTED)
    internal_cat = next(c for c, t in CATEGORY_TO_TIER.items() if t == Tier.INTERNAL)
    scores = {cat: 0.0 for cat in CATEGORY_TO_TIER}
    scores[restricted_cat] = 0.85
    scores[internal_cat] = 0.9  # higher score, but lower tier
    tier, triggered = zero_shot_tier(scores)
    assert tier == Tier.RESTRICTED
    assert triggered[0][2] == Tier.RESTRICTED


def test_zero_shot_tier_below_restricted_floor() -> None:
    # 0.55 is below the 0.70 restricted floor — should NOT escalate.
    restricted_cat = next(c for c, t in CATEGORY_TO_TIER.items() if t == Tier.RESTRICTED)
    scores = {cat: 0.0 for cat in CATEGORY_TO_TIER}
    scores[restricted_cat] = 0.55
    tier, _ = zero_shot_tier(scores)
    assert tier == Tier.PUBLIC


def test_short_name_extracts_first_clause() -> None:
    cat = "personally identifiable information such as social security numbers, full names"
    assert short_name(cat) == "personally identifiable information"


# --- Presidio rules ---


def test_corporate_email_localparts_recognised() -> None:
    assert email_localpart_is_corporate("press@example.com")
    assert email_localpart_is_corporate("info@example.com")
    assert not email_localpart_is_corporate("j.smith@example.com")


def test_non_latin_filter() -> None:
    assert _is_predominantly_non_latin("Іван Петренко")
    assert not _is_predominantly_non_latin("John Smith")
    assert not _is_predominantly_non_latin("")


def test_presidio_tier_restricted_entity_escalates() -> None:
    summary = {
        "US_SSN": {"count": 1, "max_score": 0.85, "samples": ["12*-*-***"], "raw_values": ["123-45-6789"]},
    }
    assert presidio_tier(summary) == Tier.RESTRICTED


def test_presidio_tier_single_role_email_does_not_escalate() -> None:
    summary = {
        "EMAIL_ADDRESS": {
            "count": 1,
            "max_score": 0.85,
            "samples": ["pr*****ss"],
            "raw_values": ["press@example.com"],
        }
    }
    assert presidio_tier(summary) == Tier.PUBLIC


def test_presidio_tier_person_plus_phone_escalates_to_confidential() -> None:
    summary = {
        "PERSON": {"count": 1, "max_score": 0.90, "samples": ["Jo**mi**"], "raw_values": ["John Smith"]},
        "PHONE_NUMBER": {"count": 1, "max_score": 0.85, "samples": [], "raw_values": ["+44 7700 900123"]},
    }
    assert presidio_tier(summary) == Tier.CONFIDENTIAL


def test_filter_drops_cyrillic_person() -> None:
    summary = {
        "PERSON": {
            "count": 1,
            "max_score": 0.95,
            "samples": ["Ів***ко"],
            "raw_values": ["Іван Петренко"],
        }
    }
    filtered = _filter_by_floor(summary)
    assert "PERSON" not in filtered or filtered["PERSON"]["count"] == 0


def test_filter_keeps_latin_person() -> None:
    summary = {
        "PERSON": {
            "count": 1,
            "max_score": 0.90,
            "samples": ["Jo*****th"],
            "raw_values": ["John Smith"],
        }
    }
    filtered = _filter_by_floor(summary)
    assert filtered["PERSON"]["count"] == 1
