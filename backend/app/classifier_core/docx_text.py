"""DOCX text in two views: everything in the file, and what a reader sees.

`full` covers the body in document order (nested tables, text boxes, tracked deletions),
headers/footers, footnotes/endnotes, comments, document properties and embedded documents.
`visible` drops what Word does not show on the page: hidden (`w:vanish`), white or
near-white, and sub-2-pt runs (direct formatting or inherited from styles), deleted text,
comments, properties and embedded files.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from lxml import etree

from app.logging_config import get_logger

log = get_logger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
TEXT_TAGS = (W + "t", W + "delText", W + "tab", W + "br", W + "cr")
TINY_HALF_POINTS = 4  # w:sz is in half-points; < 2 pt is unreadable
WHITE_THEME = {"background1", "light1"}

# Part content-type suffix → (kind, shown on the page?). Order = output order.
TEXT_PARTS = [
    (".document.main+xml", True),
    (".template.main+xml", True),
    (".header+xml", True),
    (".footer+xml", True),
    (".footnotes+xml", True),
    (".endnotes+xml", True),
    (".comments+xml", False),
]
CORE_PROPS = ("title", "subject", "keywords", "comments", "category")


@dataclass(frozen=True)
class TextViews:
    full: str
    visible: str


def _off(el: Any) -> bool:
    return el.get(W + "val") in ("0", "false", "off")


def _rpr_props(rpr: Any) -> dict[str, Any]:
    """The visibility-relevant properties set in one w:rPr (absent keys = not set)."""
    out: dict[str, Any] = {}
    if rpr is None:
        return out
    if (v := rpr.find(W + "vanish")) is not None:
        out["vanish"] = not _off(v)
    if (c := rpr.find(W + "color")) is not None:
        out["color"] = (c.get(W + "val") or "auto", c.get(W + "themeColor"))
    if (s := rpr.find(W + "sz")) is not None and (s.get(W + "val") or "").isdigit():
        out["sz"] = int(s.get(W + "val"))
    return out


class _Styles:
    """Resolves run properties through rStyle / pStyle `basedOn` chains and docDefaults."""

    def __init__(self, root: Any | None) -> None:
        self.styles: dict[str, tuple[dict[str, Any], str | None]] = {}
        self.defaults: dict[str, Any] = {}
        self.default_para: str | None = None
        if root is None:
            return
        for st in root.iter(W + "style"):
            sid = st.get(W + "styleId")
            based = st.find(W + "basedOn")
            self.styles[sid] = (
                _rpr_props(st.find(W + "rPr")),
                based.get(W + "val") if based is not None else None,
            )
            if st.get(W + "type") == "paragraph" and st.get(W + "default") in ("1", "true"):
                self.default_para = sid
        dflt = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        self.defaults = _rpr_props(dflt)

    def _chain(self, sid: str | None) -> list[dict[str, Any]]:
        out, seen = [], set()
        while sid and sid in self.styles and sid not in seen:
            seen.add(sid)
            props, sid = self.styles[sid]
            out.append(props)
        return out

    def effective(self, run: Any, para: Any) -> dict[str, Any]:
        rpr = run.find(W + "rPr") if run is not None else None
        rstyle = rpr.find(W + "rStyle") if rpr is not None else None
        ppr = para.find(W + "pPr")
        pstyle = ppr.find(W + "pStyle") if ppr is not None else None
        layers = [_rpr_props(rpr)]
        layers += self._chain(rstyle.get(W + "val") if rstyle is not None else None)
        layers += self._chain(pstyle.get(W + "val") if pstyle is not None else self.default_para)
        layers.append(self.defaults)
        eff: dict[str, Any] = {}
        for layer in layers:  # first layer that sets a property wins
            for k, v in layer.items():
                eff.setdefault(k, v)
        return eff


def _near_white(color: tuple[str, str | None] | None) -> bool:
    # shortcut: ignores highlight/shading, so white-on-dark counts as hidden; full view keeps it
    if color is None:
        return False
    val, theme = color
    if val.lower() != "auto" and len(val) == 6:
        try:
            return all(int(val[i : i + 2], 16) >= 0xF0 for i in (0, 2, 4))
        except ValueError:
            return False
    return theme in WHITE_THEME


def _hidden(props: dict[str, Any]) -> bool:
    sz = props.get("sz")
    return (
        bool(props.get("vanish"))
        or _near_white(props.get("color"))
        or (sz is not None and sz < TINY_HALF_POINTS)
    )


def _part_lines(root: Any, styles: _Styles, shown: bool) -> tuple[list[str], list[str]]:
    full, visible = [], []
    for para in root.iter(W + "p"):
        f_parts, v_parts = [], []
        for node in para.iter(*TEXT_TAGS):
            # text boxes nest paragraphs; each node belongs to its nearest paragraph only
            if next(node.iterancestors(W + "p")) is not para:
                continue
            if any(a.tag == MC_FALLBACK for a in node.iterancestors()):
                continue  # mc:Fallback duplicates mc:Choice (old-Word copy of text boxes)
            tag = node.tag
            text = "\t" if tag == W + "tab" else "\n" if tag in (W + "br", W + "cr") else node.text
            if not text:
                continue
            f_parts.append(text)
            run = next(node.iterancestors(W + "r"), None)
            deleted = tag == W + "delText" or any(
                a.tag == W + "moveFrom" for a in node.iterancestors()
            )
            if shown and not deleted and not _hidden(styles.effective(run, para)):
                v_parts.append(text)
        if f := "".join(f_parts).strip():
            full.append(f)
        if v := "".join(v_parts).strip():
            visible.append(v)
    return full, visible


def _embedded_texts(package: Any) -> list[str]:
    """Text of documents embedded in the package (depth 1: no recursion into them)."""
    from app.classifier_core.extract import STREAM_EXTRACTORS

    out = []
    for part in package.iter_parts():
        name = str(part.partname)
        ext = Path(name).suffix.lower()
        if name.startswith("/word/embeddings/") and ext in STREAM_EXTRACTORS:
            try:
                if text := STREAM_EXTRACTORS[ext](io.BytesIO(part.blob)).strip():
                    out.append(text)
            except Exception as exc:  # noqa: BLE001 — a broken embedded must not hide the rest
                log.warning("extract.embedded_failed", error=str(exc))
                continue
    return out


def docx_views(src: Path | IO[bytes]) -> TextViews:
    import docx

    doc = docx.Document(src)  # type: ignore[arg-type]
    package = doc.part.package
    parts = list(package.iter_parts())
    styles_part = next((p for p in parts if p.content_type.endswith(".styles+xml")), None)
    styles = _Styles(etree.fromstring(styles_part.blob) if styles_part is not None else None)

    full: list[str] = []
    visible: list[str] = []
    for suffix, shown in TEXT_PARTS:
        for part in parts:
            if part.content_type.endswith(suffix):
                f, v = _part_lines(etree.fromstring(part.blob), styles, shown)
                full += f
                visible += v

    cp = doc.core_properties
    full += [str(val) for k in CORE_PROPS if (val := getattr(cp, k, None))]
    for part in parts:
        if part.content_type.endswith("custom-properties+xml"):
            root = etree.fromstring(part.blob)
            full += [t.strip() for t in root.itertext() if t.strip()]
    full += _embedded_texts(package)
    return TextViews(full="\n".join(full), visible="\n".join(visible))
