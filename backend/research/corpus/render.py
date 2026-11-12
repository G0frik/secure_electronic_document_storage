"""Render canonical corpus markdown to DOCX, PDF and TXT (the formats the attack carriers need).

    python -m research.corpus.render <corpus_dir>      # writes <corpus_dir>/renders/<id>.<lang>.{docx,pdf,txt}

Only the markdown this corpus uses is understood: `# ` / `## ` headings, a `Subject:` first line, blank-line
paragraphs with hard line breaks inside them. Everything is plain body text otherwise, so the renderings carry
the same words as the canonical text and nothing else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import docx
from fpdf import FPDF

# fonts-dejavu-core in the image; the PDF core fonts have no Cyrillic
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def blocks(text: str) -> list[tuple[str, str]]:
    """Markdown → [(kind, text)] with kind in h1, h2, p."""
    out = []
    for para in text.strip().split("\n\n"):
        if para.startswith("# "):
            out.append(("h1", para[2:].strip()))
        elif para.startswith("## "):
            out.append(("h2", para[3:].strip()))
        else:
            out.append(("p", para.strip()))
    return out


def to_txt(bl: list[tuple[str, str]]) -> str:
    return "\n\n".join(t for _, t in bl) + "\n"


def to_docx(bl: list[tuple[str, str]], path: Path) -> None:
    d = docx.Document()
    for kind, t in bl:
        if kind == "p":
            lines = t.split("\n")
            run = d.add_paragraph().add_run(lines[0])
            for ln in lines[1:]:
                run.add_break()
                run.add_text(ln)
        else:
            d.add_heading(t, level=1 if kind == "h1" else 2)
    d.save(path)


def to_pdf(bl: list[tuple[str, str]], path: Path) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.add_page()
    for kind, t in bl:
        size = {"h1": 15, "h2": 12.5, "p": 10.5}[kind]
        pdf.set_font("DejaVu", "B" if kind != "p" else "", size)
        pdf.multi_cell(0, size * 0.5, t, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(size * 0.35)
    pdf.output(str(path))


def render(src: Path, out_dir: Path) -> None:
    bl = blocks(src.read_text(encoding="utf-8"))
    stem = src.name.removesuffix(".md")
    (out_dir / f"{stem}.txt").write_text(to_txt(bl), encoding="utf-8")
    to_docx(bl, out_dir / f"{stem}.docx")
    to_pdf(bl, out_dir / f"{stem}.pdf")


def main() -> None:
    corpus = Path(sys.argv[1])
    out_dir = corpus / "renders"
    out_dir.mkdir(exist_ok=True)
    srcs = sorted(f for sub in ("shareable", "link_only") for f in (corpus / sub).glob("*.md"))
    for f in srcs:
        render(f, out_dir)
    print(f"rendered {len(srcs)} documents × 3 formats into {out_dir}")


if __name__ == "__main__":
    main()
