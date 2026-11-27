"""Attacks for the admin playground, built on the research generator (`research.attacks`).

Text-level attacks (A1, A2, A4, A5, A6) change the document text, which is then written as TXT (what
the research classified) or rendered to DOCX/PDF. A3 hides an A1/A2 payload in a DOCX/PDF carrier;
A7 hides the whole document. For a corpus document whose attack matches a pre-built research variant
(and the payload is not edited), that exact file is used, so results line up with the research runs.

Imports `research.*` lazily: the package exists only where ./backend is mounted (the dev stack),
which is the only place the playground runs.
"""

from __future__ import annotations

import csv
import random
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

RESEARCH_DIR = Path(__file__).resolve().parents[2] / "research"
CORPUS_DIR = RESEARCH_DIR / "corpus" / "data"
VARIANTS_DIR = RESEARCH_DIR / "results" / "attacks"
A5_SEED = 20261113  # the research generator's seed

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CONTENT_TYPES = {"txt": "text/plain", "md": "text/markdown", "docx": DOCX, "pdf": "application/pdf"}
ATTACKS = ("none", "A1", "A2", "A3", "A4", "A5", "A6", "A7")
OBFUSCATIONS = ("zero_width", "homoglyph", "separators")
A7_CARRIERS = {"docx": ("vanish", "white_1pt"), "pdf": ("invisible", "white")}


class AttackError(ValueError):
    """The attack cannot be applied to this input (shown to the admin)."""


@dataclass(frozen=True)
class Doc:
    data: bytes
    filename: str
    content_type: str

    @property
    def fmt(self) -> str:
        return Path(self.filename).suffix.lower().lstrip(".")


@dataclass(frozen=True)
class AttackSpec:
    attack: str = "none"
    lang: str = "en"  # language of the document (A7's visible line, default payload language)
    payload_lang: str = "en"
    placement: str = "start"
    carrier: str = ""  # A3: DOCX/PDF carrier; A6: obfuscation kind; A7: hiding carrier
    a3_payload: str = "A1"  # A3 hides the A1 or the A2 payload
    payload: str | None = None  # edited payload text; None = the research payload
    output_format: str = "txt"  # text-level attacks and A7: txt | docx | pdf


def _research() -> Any:
    from research import attacks

    return attacks


def catalog() -> dict[str, Any]:
    """Attacks, carriers and default payloads for the page."""
    a = _research()
    return {
        "attacks": list(ATTACKS),
        "payloads": a.PAYLOAD,
        "harmless": a.HARMLESS,
        "docx_carriers": a.DOCX_CARRIERS,
        "pdf_carriers": a.PDF_CARRIERS,
        "a7_carriers": A7_CARRIERS,
        "obfuscations": list(OBFUSCATIONS),
        "pad_words": a.PAD_WORDS,
    }


def payload_text(spec: AttackSpec) -> str:
    a = _research()
    if spec.payload is not None:
        return spec.payload
    kind = spec.a3_payload if spec.attack == "A3" else "A1" if spec.attack == "A4" else spec.attack
    return str(a.PAYLOAD[kind][spec.payload_lang])


# ---------- corpus ----------


def corpus_dirs() -> list[Path]:
    return [d for d in (CORPUS_DIR, CORPUS_DIR / "hard") if (d / "labels.csv").exists()]


@lru_cache(maxsize=1)
def corpus_index() -> list[dict[str, str]]:
    """Source documents: pair_id, lang, tier, group, words, ref (relative path of the .md)."""
    out = []
    for d in corpus_dirs():
        for r in csv.DictReader((d / "labels.csv").open(encoding="utf-8")):
            path = d / r["folder"] / f"{r['pair_id']}.{r['lang']}.md"
            if path.exists():
                out.append({
                    "ref": str(path.relative_to(CORPUS_DIR)).replace("\\", "/"),
                    "pair_id": r["pair_id"], "lang": r["lang"], "tier": r["tier"],
                    "group": r.get("group", ""), "words": r.get("words", ""),
                    "difficulty": "hard" if d.name == "hard" else "base",
                })  # fmt: skip
    return out


def corpus_doc(ref: str) -> tuple[Doc, dict[str, str]]:
    """The corpus source document `ref` (as listed by `corpus_index`) as markdown text."""
    entry = next((e for e in corpus_index() if e["ref"] == ref), None)
    if entry is None:  # only listed refs: no path traversal through `ref`
        raise AttackError("Unknown corpus document.")
    data = (CORPUS_DIR / entry["ref"]).read_bytes()
    return Doc(data, f"{entry['pair_id']}.{entry['lang']}.md", CONTENT_TYPES["md"]), entry


@lru_cache(maxsize=1)
def _variants() -> list[dict[str, str]]:
    manifest = VARIANTS_DIR / "manifest.csv"
    if not manifest.exists():
        return []
    return list(csv.DictReader(manifest.open(encoding="utf-8")))


def research_variant(pair_id: str, lang: str, spec: AttackSpec) -> Path | None:
    """The pre-built research file for this corpus document and attack, if the research made one."""
    if spec.payload is not None:
        return None
    attack_id, carrier, fmt = spec.attack, spec.carrier, spec.output_format
    if spec.attack == "none":
        attack_id, carrier = "", ""
    elif spec.attack == "A3":
        attack_id = f"A3/{spec.a3_payload}"
        a = _research()
        fmt = "docx" if carrier in a.DOCX_CARRIERS else "pdf"
    elif spec.attack == "A7":
        fmt = "docx" if carrier in A7_CARRIERS["docx"] else "pdf"
    else:  # text-level attacks exist as markdown only
        fmt = "md" if spec.output_format == "txt" else spec.output_format
        carrier = carrier if spec.attack == "A6" else ""
    if spec.attack == "none" and fmt == "txt":
        fmt = "md"
    for r in _variants():
        if (r["pair_id"], r["lang"], r["attack_id"], r["carrier"], r["format"]) != (
            pair_id, lang, attack_id, carrier, fmt,
        ):  # fmt: skip
            continue
        if r["payload_lang"] and r["payload_lang"] != spec.payload_lang:
            continue
        if spec.attack in ("A1", "A2", "A4") and r["placement"] != spec.placement:
            continue
        path = VARIANTS_DIR / fmt / r["file"]
        return path if path.exists() else None
    return None


# ---------- building ----------


def _blocks(text: str, form: bool) -> Any:
    from research.corpus.render import blocks

    return blocks(text, form=form)


def _write(text: str, fmt: str, stem: str, form: bool, tmp: Path) -> Path:
    from research.corpus.render import to_docx, to_pdf

    path = tmp / f"{stem}.{fmt}"
    if fmt == "txt":
        path.write_text(text, encoding="utf-8")
    elif fmt == "docx":
        to_docx(_blocks(text, form), path)
    elif fmt == "pdf":
        to_pdf(_blocks(text, form), path)
    else:
        raise AttackError(f"Unknown output format {fmt!r}.")
    return path


def _public_texts(lang: str) -> list[str]:
    a = _research()
    docs = a.load(corpus_dirs()) if corpus_dirs() else []
    return [d["text"] for d in docs if d["tier"] == "public" and d["lang"] == lang]


def _doc(path: Path) -> Doc:
    fmt = path.suffix.lstrip(".")
    return Doc(path.read_bytes(), path.name, CONTENT_TYPES.get(fmt, "application/octet-stream"))


def apply(doc: Doc, text: str, spec: AttackSpec, *, form: bool = False) -> Doc:
    """The attacked version of `doc` (whose extracted text is `text`)."""
    a = _research()
    stem = Path(doc.filename).stem + ("" if spec.attack == "none" else f"-{spec.attack}")
    if spec.attack == "none":
        return doc
    # shortcut: research writers take paths, so the attacked file passes through a temp dir;
    # move to in-memory writers if the playground ever runs outside the local dev stack.
    with tempfile.TemporaryDirectory(prefix="pg-") as d:
        tmp = Path(d)
        if spec.attack in ("A1", "A2", "A4"):
            if spec.placement not in ("start", "end"):
                raise AttackError("Placement must be start or end.")
            out = a.insert(text, payload_text(spec), spec.placement)
            return _doc(_write(out, spec.output_format, stem, form, tmp))
        if spec.attack == "A5":
            public = _public_texts(spec.lang)
            if not public:
                raise AttackError("A5 pads with public corpus documents; the corpus is missing.")
            out = a.preamble(public, random.Random(A5_SEED)) + "\n\n" + text  # noqa: S311
            return _doc(_write(out, spec.output_format, stem, form, tmp))
        if spec.attack == "A6":
            if spec.carrier not in OBFUSCATIONS:
                raise AttackError(f"A6 needs one of {', '.join(OBFUSCATIONS)}.")
            if not a.IDENT.search(text):
                raise AttackError("A6 found no identifiers (ID numbers, IBANs, cards, phones…).")
            out = a.obfuscate(text, spec.carrier)
            return _doc(_write(out, spec.output_format, stem, form, tmp))
        if spec.attack == "A3":
            if spec.carrier in a.DOCX_CARRIERS:
                path = tmp / f"{stem}.docx"
                if doc.fmt == "docx":  # keep the original document and its formatting
                    path.write_bytes(doc.data)
                else:
                    path = _write(text, "docx", stem, form, tmp)
                a.docx_carrier(path, spec.carrier, payload_text(spec))
                return _doc(path)
            if spec.carrier in a.PDF_CARRIERS:
                from research.corpus.render import to_pdf

                path = tmp / f"{stem}.pdf"
                to_pdf(_blocks(text, form), path, extra=a.pdf_carrier(spec.carrier, payload_text(spec)))
                if spec.carrier == "cropbox":
                    a.crop_top(path)
                return _doc(path)
            raise AttackError("Unknown A3 carrier.")
        if spec.attack == "A7":
            if spec.carrier in A7_CARRIERS["docx"]:
                path = _write(text, "docx", stem, form, tmp)
                a.docx_hide_all(path, spec.carrier, spec.lang)
                return _doc(path)
            if spec.carrier in A7_CARRIERS["pdf"]:
                path = tmp / f"{stem}.pdf"
                a.pdf_hide_all(text, path, spec.carrier, spec.lang)
                return _doc(path)
            raise AttackError("Unknown A7 carrier.")
    raise AttackError(f"Unknown attack {spec.attack!r}.")


def render_text(text: str, fmt: str, name: str = "typed") -> Doc:
    """Typed text as a document: TXT as is, DOCX/PDF through the corpus renderer."""
    with tempfile.TemporaryDirectory(prefix="pg-") as d:
        return _doc(_write(text, fmt, name, False, Path(d)))
