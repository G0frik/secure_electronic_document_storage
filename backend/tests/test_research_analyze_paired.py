"""Paired tests: cluster-adjusted McNemar, defense pairing, EN/UK twins, Holm per family."""

from __future__ import annotations

from research.analyze_paired import compare, durkalski, paired_tests


def test_durkalski_ignores_discordance_that_cancels_inside_a_document() -> None:
    assert durkalski([(3, 3), (2, 2)]) == 1.0
    assert durkalski([]) == 1.0
    # one-sided discordance spread over many documents is significant, in one document it is not
    assert durkalski([(1, 0)] * 12) < 0.001
    assert durkalski([(12, 0)]) > 0.3


def _r(cfg: str, file: str, pair: str, final: str, lang: str = "en", **kw: str) -> dict[str, str]:
    base = {"config_id": cfg, "file": file, "pair_id": pair, "lang": lang, "attack_id": "A3/A1",
            "true_tier": "restricted", "final_tier": final, "carrier": "vanish",
            "placement": "start", "format": "docx", "payload_lang": lang, "group": "id"}  # fmt: skip
    return base | kw


def test_compare_counts_robust_discordance() -> None:
    pairs = [(_r("a", "f1", "d1", "restricted"), _r("b", "f1", "d1", "public")),
             (_r("a", "f2", "d2", "public"), _r("b", "f2", "d2", "public"))]  # fmt: skip
    t = compare(pairs)
    assert (t["n_pairs"], t["n_docs"], t["b"], t["c"]) == (2, 2, 1, 0)
    assert t["robust_a"] == 0.5 and t["robust_b"] == 0.0


def test_defense_pairs_same_file_and_en_uk_pairs_twins() -> None:
    rows = [
        _r("llm:qwen35-9b@none", "en1", "d1", "public"),
        _r("llm:qwen35-9b@D2", "en1", "d1", "restricted"),
        _r("llm:qwen35-9b@none", "uk1", "d1", "restricted", lang="uk"),
        _r("llm:qwen35-9b@D2", "uk1", "d1", "restricted", lang="uk"),
    ]
    out = {(t["family"], t["comparison"]): t for t in paired_tests(rows, [])}
    d2 = out[("defense:confirmatory", "D2 vs none")]
    assert (d2["n_pairs"], d2["b"], d2["c"]) == (2, 1, 0)
    lang = out[("en_vs_uk:confirmatory", "en vs uk")]
    assert lang["n_pairs"] == 1 and (lang["b"], lang["c"]) == (0, 1)
    assert all("p_holm" in t for t in out.values())


def test_hybrid_twins_get_their_own_en_uk_family() -> None:
    rows = [
        _r(cfg, f, "d1", "restricted", lang=lang)
        for cfg in ("nli_en@none", "nli_en@none+presidio")
        for f, lang in (("en1", "en"), ("uk1", "uk"))
    ]
    fams = {
        (t["family"], t["config"]) for t in paired_tests(rows, []) if t["comparison"] == "en vs uk"
    }
    assert fams == {("en_vs_uk:confirmatory", "nli_en"), ("en_vs_uk:hybrid", "nli_en+presidio")}
