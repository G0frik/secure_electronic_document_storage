"""Attack generator: determinism, every payload in the file where it should be, channel audit."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("fpdf")  # research extra; CI installs only .[dev]

from app.classifier_core.extract import get_views  # noqa: E402
from research.attacks import HARMLESS, IDENT, PAD_WORDS, PAYLOAD, generate  # noqa: E402
from research.corpus.render import FONT_DIR  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (FONT_DIR / "DejaVuSans.ttf").exists(), reason="fonts-dejavu-core not installed"
)

SECRET = "Subject: Merit increase\n\nOlena's base salary rises to UAH 92,000. RNOKPP 0013550440, tel. +380 00 512 47 09.\n"
PUBLIC = (
    "# Press release\n\n"
    + " ".join(["The ministry opened a new service centre today."] * 60)
    + "\n"
)
HIDDEN = {"vanish", "white_1pt", "comment", "core_props", "invisible", "white", "tiny", "cropbox",
          "annotation", "metadata"}  # fmt: skip


def _corpus(tmp: Path) -> Path:
    (tmp / "shareable").mkdir(parents=True)
    (tmp / "shareable/c1.en.md").write_text(SECRET, encoding="utf-8")
    (tmp / "shareable/p1.en.md").write_text(PUBLIC, encoding="utf-8")
    with (tmp / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "lang", "tier", "group", "folder"])
        w.writerow(["c1", "en", "confidential", "id", "shareable"])
        w.writerow(["p1", "en", "public", "semantic", "shareable"])
    return tmp


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict[str, str]]]:
    corpus = _corpus(tmp_path_factory.mktemp("corpus"))
    out = tmp_path_factory.mktemp("out")
    return out, generate([corpus], out)


def test_deterministic(made: tuple[Path, list[dict[str, str]]], tmp_path: Path) -> None:
    out, rows = made
    rows2 = generate([_corpus(tmp_path / "c")], tmp_path / "o")
    assert rows == rows2
    for r in rows:
        if r["format"] == "md":
            assert (out / "md" / r["file"]).read_text(encoding="utf-8") == (
                tmp_path / "o/md" / r["file"]
            ).read_text(encoding="utf-8")


def test_only_non_public_documents_attacked(made: tuple[Path, list[dict[str, str]]]) -> None:
    _, rows = made
    assert {r["pair_id"] for r in rows} == {"c1"}


def test_every_carrier_payload_lands_where_expected(
    made: tuple[Path, list[dict[str, str]]],
) -> None:
    out, rows = made
    a3 = [r for r in rows if r["attack_id"].startswith("A3/")]
    assert len(a3) == 2 * (8 + 6)
    for r in a3:
        views = get_views(out / r["format"] / r["file"])
        payload = PAYLOAD[r["attack_id"][3:]]["en"]
        flat_full, flat_vis = " ".join(views.full.split()), " ".join(views.visible.split())
        assert payload in flat_full, r["variant_id"]
        assert (payload in flat_vis) is (r["carrier"] not in HIDDEN), r["variant_id"]
        assert "Olena" in views.visible  # the document itself stays visible


def test_reverse_attack_hides_content(made: tuple[Path, list[dict[str, str]]]) -> None:
    out, rows = made
    a7 = [r for r in rows if r["attack_id"] == "A7"]
    assert len(a7) == 4
    for r in a7:
        views = get_views(out / r["format"] / r["file"])
        assert "0013550440" in views.full and "0013550440" not in views.visible, r["variant_id"]
        assert HARMLESS["en"] in " ".join(views.visible.split())


def test_text_attacks(made: tuple[Path, list[dict[str, str]]]) -> None:
    out, rows = made

    def text(r: dict[str, str]) -> str:
        return (out / "md" / r["file"]).read_text(encoding="utf-8")

    by = {(r["attack_id"], r["carrier"], r["placement"]): r for r in rows if r["format"] == "md"}
    assert text(by[("A1", "", "start")]).split("\n")[2] == PAYLOAD["A1"]["en"]
    assert text(by[("A2", "", "end")]).rstrip().endswith(PAYLOAD["A2"]["en"])
    assert PAYLOAD["A1"]["uk"] in text(by[("A4", "", "start")])
    padded = text(by[("A5", "", "")])
    assert len(padded[: padded.index("Subject:")].split()) >= PAD_WORDS
    for how in ("zero_width", "homoglyph", "separators"):
        t = text(by[("A6", how, "")])
        assert "0013550440" not in t and "Olena" in t, how
        assert not any(m.group(0) in SECRET for m in IDENT.finditer(t)), how


def test_channel_audit(tmp_path: Path) -> None:
    from research.channel_audit import audit

    rows = {(r["format"], r["carrier"]): r for r in audit(tmp_path)}
    assert rows[("docx", "body")] == {
        **rows[("docx", "body")],
        "legacy": 1,
        "full": 1,
        "visible": 1,
    }
    # paragraph-only python-docx never saw these; full extraction does; the visible view keeps visible ones
    for carrier in ("header", "footer", "table_cell", "text_box", "comment", "core_props"):
        assert rows[("docx", carrier)]["legacy"] == 0 and rows[("docx", carrier)]["full"] == 1, (
            carrier
        )
    assert rows[("docx", "vanish")]["legacy"] == 1  # hidden runs were always read
    for carrier in ("invisible", "white", "tiny", "cropbox", "annotation", "metadata"):
        assert rows[("pdf", carrier)]["full"] == 1 and rows[("pdf", carrier)]["visible"] == 0, (
            carrier
        )
