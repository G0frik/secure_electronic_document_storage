"""Which hidden carriers reach the classifier? One crafted document per carrier, one marker each.

    python -m research.channel_audit --out research/results/channel_audit

Columns: legacy = the extractors the service used before full extraction (python-docx body paragraphs;
pdfplumber page text), full = everything in the file (what the service classifies now), visible = what a
reader sees (the second view of the two-view defense). Writes audit.csv and audit.md.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from app.classifier_core.extract import get_views
from research.attacks import DOCX_CARRIERS, PDF_CARRIERS, crop_top, docx_carrier, pdf_carrier
from research.corpus.render import blocks, to_docx, to_pdf

BASE = "# Audit document\n\n{body} is an ordinary visible paragraph.\n\nA second paragraph of ordinary text.\n"


def legacy_docx(path: Path) -> str:
    import docx

    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs if p.text)


def legacy_pdf(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _has(marker: str, text: str) -> int:
    return int(marker in re.sub(r"\s", "", text))


def audit(out: Path) -> list[dict[str, object]]:
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    cases = [("docx", c) for c in ["body", *DOCX_CARRIERS]] + [
        ("pdf", c) for c in ["body", *PDF_CARRIERS]
    ]
    for fmt, carrier in cases:
        marker = "MARK" + re.sub(r"[^A-Za-z0-9]", "", carrier).upper()
        bl = blocks(BASE.format(body=marker if carrier == "body" else "This"))
        path = out / f"{carrier}.{fmt}"
        if fmt == "docx":
            to_docx(bl, path)
            if carrier != "body":
                docx_carrier(path, carrier, marker)
            legacy = legacy_docx(path)
        else:
            to_pdf(bl, path, extra=None if carrier == "body" else pdf_carrier(carrier, marker))
            if carrier == "cropbox":
                crop_top(path)
            legacy = legacy_pdf(path)
        views = get_views(path)
        rows.append({"format": fmt, "carrier": carrier, "legacy": _has(marker, legacy),
                     "full": _has(marker, views.full), "visible": _has(marker, views.visible)})  # fmt: skip
    with (out / "audit.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    yn = {0: "no", 1: "yes"}
    md = [
        "| format | carrier | legacy extractor | full view | visible view |",
        "|---|---|---|---|---|",
    ]
    md += [f"| {r['format']} | {r['carrier']} | {yn[r['legacy']]} | {yn[r['full']]} | {yn[r['visible']]} |"
           for r in rows]  # fmt: skip
    (out / "audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    audit(args.out)
    print((args.out / "audit.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
