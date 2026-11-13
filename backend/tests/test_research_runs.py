"""Harness run safety: results written per file, resume without duplicates, engine failures."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import research.classify_dir as cd
from app.classifier_core.tiers import Tier
from research.engines import SemanticResult


class FakeLlm:
    """Stand-in for LlmEngine: fails for texts listed in `fail_on` (simulates a dead server)."""

    fail_on: set[str] = set()
    calls: list[str] = []

    def __init__(self, *a, **kw) -> None:  # type: ignore[no-untyped-def]
        self.request_version, self.max_tokens, self.template_kwargs = "t", 256, {}

    def server_info(self) -> dict[str, str]:
        return {}

    def classify(self, text: str) -> SemanticResult:
        FakeLlm.calls.append(text)
        if text.strip() in FakeLlm.fail_on:
            raise ConnectionError("server gone")
        return SemanticResult(tier=Tier.INTERNAL, raw="{}")


class FakePresidio:
    def classify(self, text: str) -> tuple[Tier, list[str]]:
        return Tier.PUBLIC, []


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cd, "LlmEngine", FakeLlm)
    monkeypatch.setattr(cd, "PresidioEngine", FakePresidio)
    FakeLlm.fail_on, FakeLlm.calls = set(), []
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(6):
        (docs / f"d{i}.txt").write_text(f"doc{i}", encoding="utf-8")
    return docs


def _run(docs: Path, out: Path, *extra: str) -> None:
    cd.main(
        [
            str(docs),
            "--configs",
            "llm",
            "--llm-label",
            "fake",
            "--out",
            str(out),
            "--run-id",
            "r",
            *extra,
        ]
    )


def _rows(out: Path) -> list[dict[str, str]]:
    with (out / "r" / "predictions.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_engine_error_is_a_row_and_resume_redoes_only_that_file(
    corpus: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    FakeLlm.fail_on = {"doc2"}
    _run(corpus, out)
    rows = _rows(out)
    assert len(rows) == 12  # 6 files x (config, +presidio), the run went on past the failure
    assert all(r["error"].startswith(cd.ENGINE_ERROR) for r in rows if r["file"] == "d2.txt")
    FakeLlm.fail_on, FakeLlm.calls = set(), []
    _run(corpus, out)  # resume: finished files kept, the failed one redone
    rows = _rows(out)
    assert FakeLlm.calls == ["doc2"]
    assert sorted(r["file"] for r in rows) == sorted(
        f"d{i}.txt" for i in range(6) for _ in range(2)
    )
    assert not any(r["error"] for r in rows)
    assert json.loads((out / "r" / "manifest.json").read_text(encoding="utf-8"))["status"] == "done"


def test_consecutive_engine_failures_abort_but_keep_results(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    FakeLlm.fail_on = {f"doc{i}" for i in range(1, 6)}
    with pytest.raises(SystemExit) as exc:
        _run(corpus, out)
    assert exc.value.code == 3
    rows = _rows(out)
    assert {r["file"] for r in rows if not r["error"]} == {"d0.txt"}  # written before the abort
    assert (
        json.loads((out / "r" / "manifest.json").read_text(encoding="utf-8"))["status"] == "aborted"
    )


def test_files_option_limits_the_run(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    pick = tmp_path / "pick.txt"
    pick.write_text("d1.txt\nd4.txt\n", encoding="utf-8")
    _run(corpus, out, "--files", str(pick))
    assert {r["file"] for r in _rows(out)} == {"d1.txt", "d4.txt"}
