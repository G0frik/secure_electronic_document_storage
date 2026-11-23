"""NLI sliding windows: the whole document is scored, each category keeps its highest window score."""

from __future__ import annotations

from app.classifier_core import zero_shot
from app.classifier_core.tiers import Tier
from research.engines import NliEngine

PUBLIC_CAT = zero_shot.CATEGORIES[-1]
MEDICAL_CAT = next(c for c in zero_shot.CATEGORIES if c.startswith("medical"))


def test_word_windows_cover_every_word_with_overlap() -> None:
    words = [f"w{i}" for i in range(1000)]
    chunks = zero_shot.word_windows(" ".join(words), 400, overlap=50)
    assert [len(c.split()) for c in chunks] == [400, 400, 300]
    assert chunks[1].split()[0] == "w350"  # 50 words shared with the previous window
    assert {w for c in chunks for w in c.split()} == set(words)


def test_short_text_is_one_unchanged_window() -> None:
    text = "Short  memo\nwith odd   spacing."
    assert zero_shot.word_windows(text, 400) == [text]
    assert len(zero_shot.word_windows(" ".join(["x"] * 400), 400)) == 1
    assert len(zero_shot.word_windows(" ".join(["x"] * 401), 400)) == 2


def _fake_pipeline(calls: list[str]):  # type: ignore[no-untyped-def]
    """Public text everywhere; a window that mentions a diagnosis scores high on medical records."""

    def run(text: str, candidate_labels: list[str], **_: object) -> dict[str, list]:
        calls.append(text)
        med = 0.9 if "diagnosis" in text else 0.05
        scores = [0.8 if c == PUBLIC_CAT else med if c == MEDICAL_CAT else 0.05 for c in candidate_labels]
        return {"labels": candidate_labels, "scores": scores}

    return run


def test_padding_cannot_hide_content_after_the_first_window() -> None:
    doc = " ".join(["press release text"] * 300) + " patient diagnosis follows"  # 903 words
    calls: list[str] = []
    scores = zero_shot.zero_shot_classify(_fake_pipeline(calls), doc, 400)
    assert len(calls) == 3
    assert zero_shot.zero_shot_tier(scores)[0] is Tier.RESTRICTED
    first_only = zero_shot.zero_shot_classify(_fake_pipeline([]), doc, 400, windows=False)
    assert zero_shot.zero_shot_tier(first_only)[0] is Tier.PUBLIC


def test_research_engine_windows_only_for_windowed_config(monkeypatch) -> None:
    doc = " ".join(["press release text"] * 300) + " patient diagnosis follows"
    sent: dict[str, list[str]] = {"nli_en": [], "nli_en_w": []}

    def fake_remote(self: NliEngine, text: str) -> dict[str, float]:
        sent[self.config_id].append(text)
        out = _fake_pipeline([])(text, zero_shot.CATEGORIES)
        return dict(zip(out["labels"], out["scores"], strict=True))

    monkeypatch.setattr(NliEngine, "_remote_scores", fake_remote)
    old = NliEngine("nli_en", "http://nli").classify(doc)
    new = NliEngine("nli_en_w", "http://nli").classify(doc)
    assert (old.tier, old.truncated, len(sent["nli_en"])) == (Tier.PUBLIC, True, 1)
    assert (new.tier, new.truncated, len(sent["nli_en_w"])) == (Tier.RESTRICTED, False, 3)
