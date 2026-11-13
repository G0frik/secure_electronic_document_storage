"""Full vs visible text extraction for DOCX and PDF: every carrier, one marker each."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from lxml import etree

from app.classifier_core.docx_text import docx_views
from app.classifier_core.extract import get_text, get_views
from app.classifier_core.pdf_text import pdf_views

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

TEXTBOX_XML = f"""
<w:r xmlns:w="{W_NS}"
     xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
     xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
     xmlns:v="urn:schemas-microsoft-com:vml">
  <mc:AlternateContent>
    <mc:Choice Requires="wps">
      <wps:txbx><w:txbxContent><w:p><w:r><w:t>TEXTBOX_TEXT</w:t></w:r></w:p></w:txbxContent></wps:txbx>
    </mc:Choice>
    <mc:Fallback>
      <v:textbox><w:txbxContent><w:p><w:r><w:t>TEXTBOX_TEXT</w:t></w:r></w:p></w:txbxContent></v:textbox>
    </mc:Fallback>
  </mc:AlternateContent>
</w:r>"""

DELETED_XML = f"""
<w:del xmlns:w="{W_NS}" w:id="1" w:author="x" w:date="2026-01-01T00:00:00Z">
  <w:r><w:delText>DELETED_TEXT</w:delText></w:r>
</w:del>"""


def _docx_bytes(body: str) -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(body)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _make_docx(path: Path) -> None:
    import docx
    from docx.enum.style import WD_STYLE_TYPE
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    p = d.add_paragraph("Visible body ")
    p.add_run("HIDDEN_VANISH").font.hidden = True
    p.add_run("WHITE_RUN").font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.add_run("TINY_RUN").font.size = Pt(1)
    style = d.styles.add_style("Sneaky", WD_STYLE_TYPE.CHARACTER)
    style.font.hidden = True
    p.add_run("STYLE_HIDDEN", style="Sneaky")
    p._p.append(etree.fromstring(DELETED_XML))
    d.add_paragraph()._p.append(etree.fromstring(TEXTBOX_XML))

    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "TABLE_CELL"
    table.cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = "NESTED_CELL"

    sec = d.sections[0]
    sec.header.paragraphs[0].text = "HEADER_TEXT"
    sec.footer.paragraphs[0].text = "FOOTER_TEXT"
    commented = d.add_paragraph("commented")
    d.add_comment(commented.runs, text="COMMENT_TEXT", author="x")
    d.core_properties.title = "PROP_TITLE"

    inner = Part(
        PackURI("/word/embeddings/inner.docx"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx_bytes("EMBEDDED_TEXT"),
        d.part.package,
    )
    d.part.relate_to(inner, RT.PACKAGE)
    d.save(path)


DOCX_VISIBLE = ["Visible body", "TEXTBOX_TEXT", "TABLE_CELL", "NESTED_CELL", "HEADER_TEXT",
                "FOOTER_TEXT", "commented"]  # fmt: skip
DOCX_HIDDEN = ["HIDDEN_VANISH", "WHITE_RUN", "TINY_RUN", "STYLE_HIDDEN", "DELETED_TEXT",
               "COMMENT_TEXT", "PROP_TITLE", "EMBEDDED_TEXT"]  # fmt: skip


def test_docx_full_has_every_carrier_visible_only_what_a_reader_sees(tmp_path: Path) -> None:
    path = tmp_path / "carriers.docx"
    _make_docx(path)
    views = docx_views(path)
    for marker in DOCX_VISIBLE + DOCX_HIDDEN:
        assert marker in views.full, marker
    for marker in DOCX_VISIBLE:
        assert marker in views.visible, marker
    for marker in DOCX_HIDDEN:
        assert marker not in views.visible, marker
    assert views.full.count("TEXTBOX_TEXT") == 1  # mc:Fallback copy skipped
    assert get_text(path) == views.full
    assert docx_views(io.BytesIO(path.read_bytes())) == views


def _make_pdf(path: Path) -> None:
    from fpdf import FPDF
    from fpdf.enums import TextMode

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.text(20, 20, "VISIBLE_PDF")
    pdf.text_mode = TextMode.INVISIBLE
    pdf.text(20, 30, "INVISIBLE_PDF")
    pdf.text_mode = TextMode.FILL
    pdf.set_text_color(255, 255, 255)
    pdf.text(20, 40, "WHITE_PDF")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font_size(1)
    pdf.text(20, 50, "TINY_PDF")
    pdf.set_font_size(12)
    pdf.text(400, 60, "OFFPAGE_PDF")  # beyond the 210 mm page width
    pdf.text_annotation(20, 70, "NOTE_ANNOT")
    pdf.free_text_annotation("FREETEXT_ANNOT", 20, 80, 60, 10)
    pdf.set_title("META_TITLE")
    pdf.set_keywords("META_KEYWORDS")
    pdf.embed_file(bytes=_docx_bytes("PDF_ATTACHED"), basename="inner.docx")
    pdf.output(str(path))


# Minimal hand-written PDF with one filled form field (fpdf2 cannot create AcroForms).
FORM_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [4 0 R] >> >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Annots [4 0 R] >> endobj
4 0 obj << /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V (FORM_VALUE) /Rect [10 10 90 30] >>
endobj
trailer << /Root 1 0 R >>
%%EOF
"""

PDF_VISIBLE = ["VISIBLE_PDF", "FREETEXT_ANNOT"]
PDF_HIDDEN = ["INVISIBLE_PDF", "WHITE_PDF", "TINY_PDF", "OFFPAGE_PDF", "NOTE_ANNOT",
              "META_TITLE", "META_KEYWORDS", "PDF_ATTACHED"]  # fmt: skip


def test_pdf_full_has_every_carrier_visible_only_what_a_reader_sees(tmp_path: Path) -> None:
    path = tmp_path / "carriers.pdf"
    _make_pdf(path)
    views = pdf_views(path)
    for marker in PDF_VISIBLE + PDF_HIDDEN:
        assert marker in views.full, marker
    for marker in PDF_VISIBLE:
        assert marker in views.visible, marker
    for marker in PDF_HIDDEN:
        assert marker not in views.visible, marker
    assert get_text(path) == views.full


def test_pdf_crop_box_hides_text_outside_it(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    src = tmp_path / "carriers.pdf"
    _make_pdf(src)
    doc = pdfium.PdfDocument(src)
    doc[0].set_cropbox(0, 0, 595, 700)  # VISIBLE_PDF sits at y ≈ 785 pt: now cut off
    cropped = tmp_path / "cropped.pdf"
    doc.save(cropped)
    doc.close()
    views = pdf_views(cropped)
    assert "VISIBLE_PDF" in views.full
    assert "VISIBLE_PDF" not in views.visible


def test_pdf_form_values_in_both_views() -> None:
    views = pdf_views(io.BytesIO(FORM_PDF))
    assert "FORM_VALUE" in views.full
    assert "FORM_VALUE" in views.visible


@pytest.mark.parametrize("name", ["a.txt", "a.md"])
def test_views_of_plain_formats_are_identical(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("plain", encoding="utf-8")
    assert get_views(path).full == get_views(path).visible == "plain"


def test_broken_embedded_file_does_not_hide_the_rest(tmp_path: Path) -> None:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    d = docx.Document()
    d.add_paragraph("OUTER_TEXT")
    bad = Part(PackURI("/word/embeddings/bad.docx"), "application/octet-stream", b"nope",
               d.part.package)  # fmt: skip
    d.part.relate_to(bad, RT.PACKAGE)
    path = tmp_path / "bad.docx"
    d.save(path)
    assert "OUTER_TEXT" in docx_views(path).full
