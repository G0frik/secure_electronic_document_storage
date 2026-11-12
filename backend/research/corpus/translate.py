"""Machine-translate the missing language side of every corpus document with the DeepL API.

Usage (host, needs DEEPL_AUTH_KEY):  python backend/research/corpus/translate.py <corpus_dir> [--dry-run]

For each `<id>.en.md` without `<id>.uk.md` (and vice versa) in `shareable/` and `link_only/`, writes the
translation next to it and appends a row to `<corpus_dir>/translations.csv`. Paragraph breaks are kept.
Identifiers (keys, passwords, IBANs, tax numbers, phones, emails, URLs) are wrapped in <keep> tags that
DeepL leaves untouched, so the attack and detection experiments see the same identifiers in both languages.
Lines that look like config (`KEY=value`) are copied as is; only their `#` comments are translated.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.request
from xml.sax.saxutils import escape, unescape

API = "https://api-free.deepl.com/v2/translate"
LANG = {"en": "EN", "uk": "UK"}
TARGET = {"en": "EN-GB", "uk": "UK"}

PROTECT = re.compile(
    r"https?://\S+"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"
    r"|\+\d[\d ]{8,16}\d"
    r"|\(\d{3}\) \d{3}-\d{4}"
    r"|\bUA\d{27}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bsk_test_\w+"
    r"|(?<=[:=] )(?=\S*[\d%/+_!#*&-])\S{12,}"  # secret after "password: " / "api_key = ", not a long word
    r"|(?<=IPSEC_SHARED_SECRET )\S+"
    r"|\b[А-ЯҐЄІЇ]{2} \d{6}\b"
    r"|\b\d{8,10}\b"
)
CONFIG_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=")


def protect(text: str) -> str:
    out, last = [], 0
    for m in PROTECT.finditer(text):
        out += [escape(text[last : m.start()]), "<keep>", escape(m.group()), "</keep>"]
        last = m.end()
    out.append(escape(text[last:]))
    return "".join(out)


def restore(xml: str) -> str:
    return unescape(re.sub(r"</?keep>", "", xml))


def units(text: str) -> list[tuple[str, bool]]:
    """Split into (segment, translate?) keeping config lines verbatim and comments translatable."""
    if not any(CONFIG_LINE.match(ln) for ln in text.splitlines()):
        return [(p, True) for p in text.split("\n\n")]
    segs = []
    for ln in text.splitlines():
        if ln.startswith("# "):
            segs.append(("# ", False))
            segs.append((ln[2:], True))
        else:
            segs.append((ln, False))
        segs.append(("\n", False))
    return segs


def deepl(texts: list[str], src: str, tgt: str, key: str) -> list[str]:
    body = json.dumps(
        {
            "text": texts,
            "source_lang": LANG[src],
            "target_lang": TARGET[tgt],
            "tag_handling": "xml",
            "ignore_tags": ["keep"],
            "preserve_formatting": True,
        }
    ).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed https endpoint
        return [t["text"] for t in json.load(r)["translations"]]


def translate_text(text: str, src: str, tgt: str, key: str) -> str:
    segs = units(text)
    todo = [protect(s) for s, tr in segs if tr and s.strip()]
    done = iter(restore(t) for t in deepl(todo, src, tgt, key)) if todo else iter(())
    parts = [next(done) if tr and s.strip() else s for s, tr in segs]
    joined = "".join(parts) if any(not tr for _, tr in segs) else "\n\n".join(parts)
    return joined.rstrip("\n") + "\n"


def main() -> None:
    corpus = pathlib.Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    key = os.environ.get("DEEPL_AUTH_KEY", "")
    if not key and not dry:
        sys.exit("DEEPL_AUTH_KEY is not set")
    log = corpus / "translations.csv"
    new_log = not log.exists()
    with log.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["doc_id", "src_lang", "tgt_lang", "src_chars", "engine", "date"])
        for src_file in sorted(corpus.glob("*/*.md")):
            if src_file.parent.name not in ("shareable", "link_only"):
                continue
            doc_id, src = src_file.name.rsplit(".", 2)[0], src_file.name.rsplit(".", 2)[1]
            tgt = "uk" if src == "en" else "en"
            out = src_file.with_name(f"{doc_id}.{tgt}.md")
            if out.exists():
                continue
            text = src_file.read_text(encoding="utf-8")
            print(doc_id, src, "->", tgt, len(text), "chars")
            if dry:
                continue
            out.write_text(translate_text(text, src, tgt, key), encoding="utf-8")
            w.writerow([doc_id, src, tgt, len(text), "deepl-api-free", dt.date.today().isoformat()])


if __name__ == "__main__":
    main()
