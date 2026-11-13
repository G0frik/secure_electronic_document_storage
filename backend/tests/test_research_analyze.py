"""Research analysis: Wilson CI, exact McNemar, Holm, clean metrics."""

from __future__ import annotations

import pytest

from research.analyze import holm, macro_f1, mcnemar_exact, metrics, wilson


def test_wilson_known_values() -> None:
    lo, hi = wilson(8, 10)  # statsmodels proportion_confint(8, 10, method="wilson")
    assert lo == pytest.approx(0.4902, abs=1e-4)
    assert hi == pytest.approx(0.9433, abs=1e-4)
    assert wilson(0, 10)[0] == 0.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_mcnemar_exact_known_values() -> None:
    assert mcnemar_exact(1, 6) == pytest.approx(0.125)  # 2 * (1 + 7) / 2**7
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(6, 1) == mcnemar_exact(1, 6)
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 0) == 1.0


def test_holm_keeps_input_order_and_is_monotone() -> None:
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])
    assert holm([]) == []


def _r(true: str, pred: str) -> dict[str, str]:
    return {"true_tier": true, "final_tier": pred, "latency_ms": "10"}


def test_metrics_invalid_is_wrong_but_not_under() -> None:
    rows = [
        _r("restricted", "restricted"),
        _r("restricted", "public"),  # under by 3
        _r("public", "internal"),  # over by 1
        _r("internal", ""),  # invalid
    ]
    m = metrics(rows)
    assert m["acc"] == 0.25
    assert m["under"] == 0.25
    assert m["over"] == 0.25
    assert m["invalid"] == 1
    assert m["mae"] == pytest.approx(4 / 3)


def test_macro_f1_perfect_and_partial() -> None:
    assert macro_f1([_r("public", "public"), _r("restricted", "restricted")]) == 1.0
    # public: P=1/2 R=1 F1=2/3; internal: P=0 R=0 F1=0 → mean 1/3
    assert macro_f1([_r("public", "public"), _r("internal", "public")]) == pytest.approx(1 / 3)
