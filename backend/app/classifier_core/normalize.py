"""
Canonicalize-before-inspect layer for the document classifier (D6, defence against A6).

- Fold tables come from ICU / UTS #39 (see gen_tables.py); nothing hand-written.
- Folding is token-scoped so ordinary Ukrainian text is never rewritten.
- Every replacement is 1:1, plus an index map, so detector spans found on the
  canonical view map back to exact offsets in the original document.
- The original document is never modified; this only builds a detection view.
- Separator obfuscation is undone too: ` [at] ` / ` [dot] ` in e-mail addresses, and dot-like
  separators (U+00B7 and similar) inside a token that holds digits (`30·12·34·56·78`).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_T = json.loads((Path(__file__).with_name("confusable_tables.json")).read_text("utf-8"))
TO_DIGIT: dict[str, str] = _T["to_digit"]
TO_LATIN: dict[str, str] = _T["to_latin"]
TO_CYRILLIC: dict[str, str] = _T["to_cyrillic"]
TABLES_META = _T["_meta"]

# Default_Ignorable-ish characters used to split tokens invisibly
_INVISIBLE = re.compile(r"[­͏؜ᅟᅠ឴឵᠋-᠏"
                        r"​-‏‪-‮⁠-⁯ㅤ︀-️﻿]")
_TOKEN = re.compile(r"\S+")

EVASION_REASONS = frozenset({"digit", "email", "mixed", "invisible", "separator"})
# Dot-like separators an attacker puts between digits; not used inside numbers in ordinary text.
_SEPARATORS = frozenset("·•∙⋅・")
_BRACKETED = re.compile(r"\s*\[(at|dot)\]\s*", re.IGNORECASE)


def _script(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    name = unicodedata.name(ch, "")
    for s in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(s):
            return s
    return "OTHER"


@dataclass(frozen=True)
class Fold:
    start: int              # offsets in the ORIGINAL text
    end: int
    original: str
    canonical: str
    reason: str             # digit | email | mixed | invisible | compat


@dataclass
class CanonicalText:
    original: str
    text: str
    idx_map: list[int]      # canonical index -> original index
    folds: list[Fold] = field(default_factory=list)

    def span_to_original(self, start: int, end: int) -> tuple[int, int]:
        return self.idx_map[start], self.idx_map[end - 1] + 1

    def folds_in(self, start: int, end: int) -> list[Fold]:
        """Folds overlapping an ORIGINAL-text span."""
        return [f for f in self.folds if f.start < end and start < f.end]

    @property
    def evasion_suspected(self) -> bool:
        return any(f.reason in EVASION_REASONS for f in self.folds)


# Legitimate identifiers that mix letters and digits on purpose: never digit-fold.
KNOWN_FORMATS = [
    re.compile(r"^[А-ЯҐЄІЇ]{2}\d{6}[.,;:)]?$"),      # UA passport, old booklet (series + number)
]

def _IS_DIGIT(c: str) -> bool:  # noqa: N802 (kept from the original module)
    return "0" <= c <= "9"


def _fold_digit_runs(tok: str) -> str:
    """Fold runs of digit-lookalikes only where the run directly touches a real digit.
    '(7ІЗ)' -> '(713)', 'ОІ42' -> '0142', but '15/З' and 'з 2020' stay as they are."""
    out, i, n = list(tok), 0, len(tok)
    while i < n:
        if tok[i] in TO_DIGIT and not _IS_DIGIT(tok[i]):
            j = i
            while j < n and tok[j] in TO_DIGIT and not _IS_DIGIT(tok[j]):
                j += 1
            if (i > 0 and _IS_DIGIT(tok[i - 1])) or (j < n and _IS_DIGIT(tok[j])):
                for k in range(i, j):
                    out[k] = TO_DIGIT[tok[k]]
            i = j
        else:
            i += 1
    return "".join(out)


def _fold_token(tok: str) -> tuple[str, str | None]:
    reason = None
    # 1) digit context: lookalike run glued to a real digit, unless a known legit format
    if any(_IS_DIGIT(c) for c in tok) and not any(p.match(tok) for p in KNOWN_FORMATS):
        new = _fold_digit_runs(tok)
        if new != tok:
            tok, reason = new, "digit"
    # 2) e-mail / URL-ish: force Latin
    if "@" in tok or "://" in tok:
        new = "".join(TO_LATIN.get(c, c) for c in tok)
        return (new, "email") if new != tok else (tok, reason)
    # 3) mixed Latin + Cyrillic/Greek: fold the minority script into the majority
    scripts = [s for c in tok if (s := _script(c))]
    if "LATIN" in scripts and len(set(scripts)) > 1:
        n_lat = scripts.count("LATIN")
        table = TO_LATIN if n_lat * 2 >= len(scripts) else TO_CYRILLIC
        new = "".join(table.get(c, c) for c in tok)
        if new != tok:
            return new, reason or "mixed"
    return tok, reason


def _is_dropped_separator(text: str, i: int) -> bool:
    """A dot-like separator between two alphanumerics, inside a whitespace-free run holding a digit."""
    if text[i] not in _SEPARATORS or not (0 < i < len(text) - 1):
        return False
    if not (text[i - 1].isalnum() and text[i + 1].isalnum()):
        return False
    lo, hi = i, i
    while lo > 0 and not text[lo - 1].isspace():
        lo -= 1
    while hi < len(text) - 1 and not text[hi + 1].isspace():
        hi += 1
    return any(c.isdigit() for c in text[lo : hi + 1])


def canonicalize(text: str) -> CanonicalText:
    chars: list[str] = []
    idx: list[int] = []
    bracketed = {m.start(): m for m in _BRACKETED.finditer(text)}
    skip_to = 0
    for i, ch in enumerate(text):
        if i < skip_to:
            continue
        if (m := bracketed.get(i)) is not None:  # ' [at] ' -> '@', ' [dot] ' -> '.'
            chars.append("@" if m.group(1).lower() == "at" else ".")
            idx.append(i)
            skip_to = m.end()
            continue
        if _INVISIBLE.match(ch) or _is_dropped_separator(text, i):
            continue
        if ch.isdigit() and not ch.isascii():           # ١٢٣, १२३, ...
            ch = str(unicodedata.digit(ch, ch))
        for out in unicodedata.normalize("NFKC", ch):   # per-char NFKC keeps offsets traceable
            chars.append(out)
            idx.append(i)

    s = "".join(chars)
    parts: list[str] = []
    folds: list[Fold] = []
    pos = 0
    for m in _TOKEN.finditer(s):
        parts.append(s[pos:m.start()])
        new, reason = _fold_token(m.group())
        o_start, o_end = idx[m.start()], idx[m.end() - 1] + 1
        orig = text[o_start:o_end]
        if new != orig:
            if _BRACKETED.search(orig) or any(c in _SEPARATORS for c in orig):
                reason = "separator"
            reason = reason or ("invisible" if _INVISIBLE.search(orig) else "compat")
            folds.append(Fold(o_start, o_end, orig, new, reason))
        parts.append(new)
        pos = m.end()
    parts.append(s[pos:])
    return CanonicalText(original=text, text="".join(parts), idx_map=idx, folds=folds)
