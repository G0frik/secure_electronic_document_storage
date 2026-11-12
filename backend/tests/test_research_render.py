import pytest

pytest.importorskip("fpdf")  # research extra; CI installs only .[dev]

from app.classifier_core.extract import get_text  # noqa: E402
from research.corpus.render import FONT_DIR, render  # noqa: E402

DOC = (
    "# Заява про конфіденційність\n\n"
    "Пацієнт Коваленко, РНОКПП 0013550440.\nSecond line, English.\n\n"
    "## Section two\n\n"
    "password: w707%kPXDXQejbWLPa%0\n"
)


@pytest.mark.skipif(
    not (FONT_DIR / "DejaVuSans.ttf").exists(), reason="fonts-dejavu-core not installed"
)
def test_every_rendering_reaches_the_extractor(tmp_path):
    src = tmp_path / "x.uk.md"
    src.write_text(DOC, encoding="utf-8")
    render(src, tmp_path)
    for ext in ("txt", "docx", "pdf"):
        text = get_text(tmp_path / f"x.uk.{ext}")
        for needle in (
            "Заява про конфіденційність",
            "Коваленко",
            "0013550440",
            "w707%kPXDXQejbWLPa%0",
            "Section two",
        ):
            assert needle in text, (ext, needle)
