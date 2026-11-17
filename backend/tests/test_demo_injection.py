"""Injection demo on the real fixtures, with a stub classifier standing in for the worker's model:
it obeys the hidden directive when it can see it (as the attacked LLMs did)."""

from __future__ import annotations

import pytest

from app.classifier_core import ClassifyResult
from app.classifier_core.tiers import Tier
from app.config import settings
from app.models.classification import ClassificationStatus
from app.services import classification, demo_injection


def _gullible(text: str) -> ClassifyResult:
    if "Classification: PUBLIC" in text:
        tier = Tier.PUBLIC
    elif "PERSON_1" in text:  # the court judgment
        tier = Tier.RESTRICTED
    else:
        tier = Tier.PUBLIC
    return ClassifyResult(final_tier=tier, zero_shot_tier=tier, presidio_tier=Tier.PUBLIC)


@pytest.fixture
def worker(monkeypatch, seeded_user):  # type: ignore[no-untyped-def]
    """Replace waiting for the Celery worker with an in-process classification."""
    monkeypatch.setattr(demo_injection, "OWNER", seeded_user.email)

    def run(file_id, timeout, poll=2.0):  # type: ignore[no-untyped-def]
        row = classification.get_latest(file_id)
        if row.status in (ClassificationStatus.PENDING, ClassificationStatus.RUNNING):
            row = classification.run_classification(file_id, classifier_fn=_gullible)
        return row

    monkeypatch.setattr(demo_injection, "wait_for_result", run)


def test_hidden_directive_makes_a_restricted_file_shareable_without_defenses(
    worker, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "")
    lines: list[str] = []
    out = demo_injection.injection(lines.append, timeout=5)
    assert out["tier"] == "public"
    assert out["link"].startswith("CREATED")


def test_d2_keeps_it_restricted_and_refuses_the_link(worker, monkeypatch) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D2")
    lines: list[str] = []
    out = demo_injection.injection(lines.append, timeout=5)
    assert out["tier"] == "restricted"
    assert out["link"].startswith("REFUSED (ShareLinkTierBlockedError")
    assert any("defenses D2" in line for line in lines)


def test_toctou_link_refused_for_the_new_restricted_version(worker) -> None:
    lines: list[str] = []
    out = demo_injection.toctou(lines.append, timeout=5)
    assert out["link"].startswith("CREATED")
    assert out["while version 2 is being classified"].startswith("REFUSED")
    assert out["after classification"] == "REFUSED (ShareLinkTierBlockedError)"
