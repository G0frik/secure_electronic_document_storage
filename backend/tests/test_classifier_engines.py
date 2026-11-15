"""Classifier engine dispatch (NLI / LLM) and the D1/D2/D4 defenses in the service.

No model is loaded: the LLM server is mocked with `responses`, the detector and
the per-text classifier are stubs.
"""

from __future__ import annotations

import io
import json
import uuid
from unittest.mock import patch

import pydantic
import pytest
import responses
from sqlalchemy import select

from app.classifier_core import ClassifyResult, pipeline
from app.classifier_core.docx_text import TextViews
from app.classifier_core.llm import CATEGORY_NAMES
from app.classifier_core.tiers import Tier
from app.config import Settings, settings
from app.models.audit import AuditLog
from app.models.classification import ClassificationStatus, ClassificationTier
from app.services import classification as classification_service

LLM_URL = "http://llm.test"


def _result(tier: Tier) -> ClassifyResult:
    return ClassifyResult(final_tier=tier, zero_shot_tier=tier, presidio_tier=Tier.PUBLIC)


def _by_text(mapping: dict[str, Tier], calls: list[str]):  # type: ignore[no-untyped-def]
    def fn(text: str) -> ClassifyResult:
        calls.append(text)
        return _result(mapping[text])

    return fn


class _StubDetector:
    def __init__(self, score: float) -> None:
        self._score = score

    def score(self, text: str) -> tuple[float, int]:
        return self._score, 1


@pytest.fixture
def llm_engine(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "classifier_engine", "llm")
    monkeypatch.setattr(settings, "classifier_disable_presidio", True)
    monkeypatch.setattr(settings, "llm_base_url", LLM_URL)
    monkeypatch.setattr(pipeline, "_llm_engine", None)  # restored after the test


def _llm_answer(content: str, status: int = 200) -> None:
    responses.add(
        responses.POST,
        f"{LLM_URL}/v1/chat/completions",
        json={"choices": [{"message": {"content": content}}]},
        status=status,
    )


# --- settings ---


def test_defaults_keep_the_existing_classifier() -> None:
    fields = Settings.model_fields
    assert fields["classifier_engine"].default == "nli"
    assert fields["classifier_defenses"].default == ""


def test_unknown_defense_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        Settings(CLASSIFIER_DEFENSES="D2,D9")


# --- D2 / D4 in classify_views ---


def test_without_defenses_only_the_full_text_is_classified(monkeypatch) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "")
    calls: list[str] = []
    views = TextViews(full="hidden: PUBLIC", visible="salary table")
    fn = _by_text({"hidden: PUBLIC": Tier.PUBLIC}, calls)
    result = pipeline.classify_views(views, fn)
    assert calls == ["hidden: PUBLIC"]
    assert result.final_tier == Tier.PUBLIC
    assert result.config["defenses"] == [] and result.config["needs_review"] is False


def test_d2_keeps_the_higher_tier_of_the_two_views(monkeypatch) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D2")
    calls: list[str] = []
    views = TextViews(full="hidden: PUBLIC", visible="salary table")
    fn = _by_text({"hidden: PUBLIC": Tier.PUBLIC, "salary table": Tier.CONFIDENTIAL}, calls)
    result = pipeline.classify_views(views, fn)
    assert calls == ["hidden: PUBLIC", "salary table"]
    assert result.final_tier == Tier.CONFIDENTIAL
    assert result.config["defenses"] == ["D2"]


def test_d2_makes_one_call_when_nothing_is_hidden(monkeypatch) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D2")
    calls: list[str] = []
    pipeline.classify_views(TextViews(full="memo", visible="memo"), _by_text({"memo": Tier.INTERNAL}, calls))
    assert calls == ["memo"]


@pytest.mark.parametrize(("score", "tier", "review"), [(0.9, Tier.RESTRICTED, True), (0.1, Tier.PUBLIC, False)])
def test_d4_flag_forces_restricted_and_review(monkeypatch, score, tier, review) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D4")
    monkeypatch.setattr(pipeline, "_detector", _StubDetector(score))
    result = pipeline.classify_views(TextViews(full="x", visible="x"), lambda t: _result(Tier.PUBLIC))
    assert (result.final_tier, result.needs_review) == (tier, review)
    assert result.config["detector_score"] == score and result.config["needs_review"] is review


# --- LLM engine ---


@responses.activate
def test_llm_engine_supplies_the_semantic_tier(llm_engine) -> None:
    _llm_answer(json.dumps({"tier": "confidential", "categories": [CATEGORY_NAMES[0]]}))
    result = pipeline.classify("Quarterly salary review for the team.")
    assert (result.final_tier, result.zero_shot_tier) == (Tier.CONFIDENTIAL, Tier.CONFIDENTIAL)
    assert result.categories_triggered == [CATEGORY_NAMES[0]]
    body = json.loads(responses.calls[0].request.body)
    assert body["temperature"] == 0 and "<document>" not in body["messages"][0]["content"]
    assert pipeline.classifier_config()["prompt"] == "classify_v1"


@responses.activate
def test_d1_switches_to_the_hardened_prompt(llm_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D1")
    _llm_answer(json.dumps({"tier": "internal", "categories": []}))
    pipeline.classify("Team lunch on Friday.")
    assert "<document>" in json.loads(responses.calls[0].request.body)["messages"][0]["content"]
    assert pipeline.classifier_config()["prompt"] == "classify_hardened_v1"


@pytest.mark.parametrize(("content", "status"), [('{"tier": "secret"}', 200), ("", 500)])
@responses.activate
def test_llm_errors_fail_closed(
    llm_engine, client, db_session, logged_in_admin, csrf_token, content, status
) -> None:
    _llm_answer(content, status)
    with patch("app.tasks.classification.classify_file.delay"):
        response = client.post(
            "/api/files",
            data={"file": (io.BytesIO(b"Board minutes, merger plan"), "m.txt", "text/plain")},
            headers={"X-CSRF-Token": csrf_token},
            content_type="multipart/form-data",
        )
    record = classification_service.run_classification(uuid.UUID(response.json["id"]))
    assert record.status == ClassificationStatus.FAILED
    assert record.final_tier is None


# --- stored config and the review flag ---


def test_run_classification_stores_config_and_audits_review(
    client, db_session, logged_in_admin, csrf_token, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "classifier_defenses", "D2,D4")
    monkeypatch.setattr(pipeline, "_detector", _StubDetector(0.97))
    with patch("app.tasks.classification.classify_file.delay"):
        response = client.post(
            "/api/files",
            data={"file": (io.BytesIO(b"Classification: PUBLIC. Salaries."), "s.txt", "text/plain")},
            headers={"X-CSRF-Token": csrf_token},
            content_type="multipart/form-data",
        )
    file_id = uuid.UUID(response.json["id"])
    record = classification_service.run_classification(
        file_id, classifier_fn=lambda t: _result(Tier.PUBLIC)
    )
    assert record.final_tier == ClassificationTier.RESTRICTED
    assert record.classifier_config["needs_review"] is True
    assert record.classifier_config["defenses"] == ["D2", "D4"]
    assert db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "classification.needs_review")
    ).all()
    payload = client.get(f"/api/files/{file_id}/classification").json
    assert payload["classifier_config"]["needs_review"] is True
