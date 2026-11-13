"""PDF text in two views: everything in the file, and what a reader sees.

`full` covers page text (including invisible, white, tiny and off-page characters),
annotations, form-field values, document metadata (Info + XMP) and embedded files.
`visible` keeps only characters drawn on the page: not render mode 3/7 (invisible),
not white or near-white, at least 2 pt, centre inside the crop box; plus form values and
FreeText annotations, which are printed on the page.
Shortcut: optional-content layers (OCG) switched off are not detected, so their text stays
in `visible`; upgrade if the channel audit shows OCG reaching the classifier unnoticed.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

from app.classifier_core.docx_text import TextViews
from app.logging_config import get_logger

log = get_logger(__name__)

INVISIBLE_MODES = {3, 7}  # 3 = neither fill nor stroke, 7 = clip only
TINY_PT = 2.0
NEAR_WHITE = 0.95
INFO_KEYS = ("Title", "Subject", "Keywords")
MAX_FIELD_DEPTH = 32


def _s(value: Any) -> str:
    """PDF string / name / bytes → text."""
    from pdfminer.psparser import PSLiteral
    from pdfminer.utils import decode_text

    if isinstance(value, PSLiteral):
        value = value.name
    if isinstance(value, bytes):
        return decode_text(value)
    return value if isinstance(value, str) else ""


def _near_white(color: Any) -> bool:
    if isinstance(color, int | float):
        return color >= NEAR_WHITE  # gray
    if isinstance(color, list | tuple):
        if len(color) == 3:  # rgb
            return all(isinstance(c, int | float) and c >= NEAR_WHITE for c in color)
        if len(color) == 4:  # cmyk: white = no ink
            return all(isinstance(c, int | float) and c <= 1 - NEAR_WHITE for c in color)
    return False


def _visible_char(ch: Any, crop: tuple[float, float, float, float]) -> bool:
    if getattr(ch, "render_mode", 0) in INVISIBLE_MODES:
        return False
    if ch.size < TINY_PT or _near_white(ch.graphicstate.ncolor):
        return False
    cx, cy = (ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2
    return bool(crop[0] <= cx <= crop[2] and crop[1] <= cy <= crop[3])


def _lines(layout: Any) -> Any:
    from pdfminer.layout import LTTextLine

    for obj in layout:
        if isinstance(obj, LTTextLine):
            yield obj
        elif hasattr(obj, "__iter__"):
            yield from _lines(obj)


def _fields(fields: Any, depth: int = 0) -> list[str]:
    from pdfminer.pdftypes import resolve1

    out: list[str] = []
    if depth > MAX_FIELD_DEPTH:
        return out
    for ref in resolve1(fields) or []:
        field = resolve1(ref)
        if not isinstance(field, dict):
            continue
        value = resolve1(field.get("V"))
        if text := _s(value).strip():
            out.append(text)
        if "Kids" in field:
            out += _fields(field["Kids"], depth + 1)
    return out


def _xmp(catalog: dict[str, Any]) -> list[str]:
    from pdfminer.pdftypes import resolve1

    stream = resolve1(catalog.get("Metadata"))
    if stream is None or not hasattr(stream, "get_data"):
        return []
    xml = stream.get_data().decode("utf-8", errors="replace")
    out = []
    for tag in ("dc:title", "dc:description", "dc:subject", "pdf:Keywords"):
        for block in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, flags=re.S):
            text = re.sub(r"<[^>]+>", " ", block)
            out += [t for t in (" ".join(text.split()),) if t]
    return out


def _embedded(catalog: dict[str, Any]) -> list[str]:
    """Text of attached files (depth 1)."""
    from pdfminer.pdftypes import resolve1

    from app.classifier_core.extract import STREAM_EXTRACTORS

    names = resolve1(resolve1(catalog.get("Names") or {}).get("EmbeddedFiles"))
    if not isinstance(names, dict):
        return []
    pairs = list(resolve1(names.get("Names")) or [])
    for kid in resolve1(names.get("Kids")) or []:  # one level of the name tree
        pairs += list(resolve1(resolve1(kid).get("Names")) or [])
    out = []
    for spec in pairs[1::2]:
        spec = resolve1(spec)
        if not isinstance(spec, dict):
            continue
        ext = Path(_s(spec.get("UF") or spec.get("F"))).suffix.lower()
        stream = resolve1(resolve1(spec.get("EF") or {}).get("F"))
        if ext in STREAM_EXTRACTORS and stream is not None:
            try:
                if text := STREAM_EXTRACTORS[ext](io.BytesIO(stream.get_data())).strip():
                    out.append(text)
            except Exception as exc:  # noqa: BLE001 — a broken attachment must not hide the rest
                log.warning("extract.attachment_failed", error=str(exc))
                continue
    return out


def pdf_views(src: Path | IO[bytes], max_chars: int | None = None) -> TextViews:
    """`max_chars` stops after the page where the full text passes it (previews)."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTChar
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1

    class Aggregator(PDFPageAggregator):
        # pdfminer drops the text render mode; keep it on each char for the visible view
        def render_string(self, textstate, seq, ncs, graphicstate):  # type: ignore[no-untyped-def]
            before = len(self.cur_item._objs)
            super().render_string(textstate, seq, ncs, graphicstate)
            for obj in self.cur_item._objs[before:]:
                setattr(obj, "render_mode", textstate.render)  # noqa: B010

    fh = open(src, "rb") if isinstance(src, str | Path) else cast("BinaryIO", src)  # noqa: SIM115
    try:
        doc = PDFDocument(PDFParser(fh))
        rsrc = PDFResourceManager()
        device = Aggregator(rsrc, laparams=LAParams(all_texts=True))
        interp = PDFPageInterpreter(rsrc, device)
        full: list[str] = []
        visible: list[str] = []
        size = 0
        for page in PDFPage.create_pages(doc):
            interp.process_page(page)
            crop = tuple(page.cropbox)
            for line in _lines(device.get_result()):
                f = line.get_text().strip()
                v = "".join(
                    c.get_text()
                    for c in line
                    if not isinstance(c, LTChar) or _visible_char(c, crop)  # type: ignore[arg-type]
                ).strip()
                if f:
                    full.append(f)
                    size += len(f)
                if v:
                    visible.append(" ".join(v.split()))
            for annot in resolve1(page.annots) or []:
                annot = resolve1(annot)
                if not isinstance(annot, dict):
                    continue
                if text := _s(resolve1(annot.get("Contents"))).strip():
                    full.append(text)
                    if _s(annot.get("Subtype")) == "FreeText":
                        visible.append(text)
            if max_chars is not None and size > max_chars:
                break
        catalog = doc.catalog
        form = resolve1(resolve1(catalog.get("AcroForm") or {}).get("Fields"))
        values = _fields(form) if form else []
        full += values
        visible += values
        for info in doc.info:
            full += [t for k in INFO_KEYS if (t := _s(resolve1(info.get(k))).strip())]
        full += [t for t in _xmp(catalog) if t not in full]
        full += _embedded(catalog)
    finally:
        if fh is not src:
            fh.close()
    return TextViews(full="\n".join(full), visible="\n".join(visible))
