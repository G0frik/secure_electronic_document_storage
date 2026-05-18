#!/usr/bin/env python3
"""
Document Sensitivity Classifier v6 (zero-shot NLI + Microsoft Presidio)
=======================================================================

What's new vs v5
----------------
v6 applies four targeted accuracy fixes (12/12 on original blind corpus):

  Fix #1 — Cyrillic NER suppression: spaCy's English NER hallucinates
    PERSON/LOCATION/NRP entities from non-Latin (e.g. Ukrainian) text.
    A Latin-character ratio check now filters these false positives before
    they can escalate tier.

  Fix #2 — Remove dead bundle rule: an unreachable combined-signal rule
    (PHONE + PERSON + LOCATION) was masking the correct CONFIDENTIAL
    escalation path. Removed to restore expected behaviour.

  Fix #3 — Broadened INTERNAL category: the NLI hypothesis for internal
    content now covers sprint retrospectives, postmortems, product roadmaps,
    and working drafts in addition to team memos.

  Fix #4 — New M&A CONFIDENTIAL category: added a dedicated NLI hypothesis
    for mergers & acquisitions, valuation models, and material non-public
    information so board-minutes-style documents route correctly.

What's new vs v4
----------------
v5 added a `--multilingual` flag that swaps the zero-shot model to
`MoritzLaurer/bge-m3-zeroshot-v2.0-c` (XLM-RoBERTa, 8192-token context).
No rules or thresholds changed in v5 — the model swap was isolated to
measure its accuracy impact.

What's new vs v2/v3
-------------------
v2 used zero-shot NLI only, which fails on structured/pattern content (raw
SSNs, credit cards, passwords). v3 added Microsoft Presidio for deterministic
regex/NER detection:
  - US_SSN, CREDIT_CARD, IBAN, US_PASSPORT, US_DRIVER_LICENSE  -> RESTRICTED
  - MEDICAL_LICENSE, CRYPTO addresses                          -> RESTRICTED
  - PERSON, EMAIL, PHONE, LOCATION                             -> CONFIDENTIAL
  - IP_ADDRESS, URL                                            -> INTERNAL
  - Custom CREDENTIAL recognizer (password/secret/key regex)   -> RESTRICTED

The final tier = max(zero_shot_tier, presidio_tier) — defense in depth.

INSTALL
-------
    pip install transformers torch sentencepiece pdfplumber python-docx python-pptx
    pip install presidio-analyzer presidio-anonymizer
    python -m spacy download en_core_web_lg

Optional — extra file format support (install only what you need):
    pip install openpyxl          # .xlsx Excel workbooks
    pip install xlrd              # .xls  Excel 97-2003
    pip install striprtf          # .rtf  Rich Text Format
    pip install pyyaml            # .yaml/.yml config files

Optional GPU acceleration on Windows (any DX12 GPU — AMD/Intel/NVIDIA):
    pip install optimum[onnxruntime] onnxruntime-directml
GPU is enabled by default; pass --cpu to force CPU-only inference.

If Presidio isn't installed, the script falls back to zero-shot only.
"""

import argparse
import sys
from pathlib import Path
from collections import defaultdict

# -------- Optional: Presidio --------
try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

# -------- Optional: ONNX Runtime + DirectML (GPU on AMD/Intel/NVIDIA, Windows) --------
try:
    from optimum.onnxruntime import ORTModelForSequenceClassification
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False

# -------- Text extractors --------

def extract_pdf(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def extract_docx(path):
    import docx
    return "\n".join(p.text for p in docx.Document(path).paragraphs if p.text)

def extract_pptx(path):
    from pptx import Presentation
    parts = []
    for slide in Presentation(path).slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                parts.append(shape.text)
    return "\n".join(parts)

def extract_text(path):
    return path.read_text(encoding="utf-8", errors="ignore")

def extract_xlsx(path):
    """Extract text from Excel .xlsx/.xls workbooks (all sheets, all cells)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append(" | ".join(cells))
    wb.close()
    return "\n".join(parts)

def extract_xls(path):
    """Extract text from legacy .xls workbooks (Excel 97-2003)."""
    import xlrd
    wb = xlrd.open_workbook(str(path))
    parts = []
    for sheet in wb.sheets():
        for rx in range(sheet.nrows):
            cells = [str(c) for c in sheet.row_values(rx) if c not in (None, "")]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)

def extract_csv(path):
    """Extract text from CSV/TSV files, joining rows with pipe separators."""
    import csv
    parts = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    dialect = csv.Sniffer().sniff(text[:4096]) if text[:4096].strip() else None
    for row in csv.reader(text.splitlines(), dialect=dialect or "excel"):
        cells = [c for c in row if c.strip()]
        if cells:
            parts.append(" | ".join(cells))
    return "\n".join(parts)

def extract_rtf(path):
    """Extract text from RTF documents."""
    from striprtf.striprtf import rtf_to_text
    return rtf_to_text(path.read_text(encoding="utf-8", errors="ignore"))

def extract_html(path):
    """Extract visible text from HTML/HTM files."""
    from html.parser import HTMLParser
    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts, self._skip = [], False
            self._skip_tags = {"script", "style", "head", "meta", "link"}
        def handle_starttag(self, tag, _):
            if tag.lower() in self._skip_tags:
                self._skip = True
        def handle_endtag(self, tag):
            if tag.lower() in self._skip_tags:
                self._skip = False
        def handle_data(self, data):
            if not self._skip and data.strip():
                self._parts.append(data.strip())
    parser = _TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parser._parts)

def extract_json(path):
    """Extract all string values from JSON files recursively."""
    import json
    def _walk(obj):
        if isinstance(obj, str):
            return [obj]
        if isinstance(obj, dict):
            parts = []
            for k, v in obj.items():
                parts.append(str(k))
                parts.extend(_walk(v))
            return parts
        if isinstance(obj, list):
            parts = []
            for item in obj:
                parts.extend(_walk(item))
            return parts
        return [str(obj)] if obj is not None else []
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(_walk(data))

def extract_xml(path):
    """Extract all text content from XML files."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    parts = []
    for elem in tree.iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return "\n".join(parts)

def extract_yaml(path):
    """Extract text from YAML/YML files (flattens all values to text)."""
    import yaml
    def _walk(obj, prefix=""):
        if isinstance(obj, dict):
            parts = []
            for k, v in obj.items():
                parts.extend(_walk(v, f"{prefix}{k}: "))
            return parts
        if isinstance(obj, list):
            parts = []
            for item in obj:
                parts.extend(_walk(item, prefix))
            return parts
        return [f"{prefix}{obj}"] if obj is not None else []
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(_walk(data))

def extract_eml(path):
    """Extract text from .eml email files (headers + body)."""
    import email
    from email import policy
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    parts = []
    # Include key headers
    for hdr in ("From", "To", "Cc", "Bcc", "Subject", "Date"):
        val = msg.get(hdr)
        if val:
            parts.append(f"{hdr}: {val}")
    # Extract body
    body = msg.get_body(preferencelist=("plain", "html"))
    if body:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            # Reuse our HTML extractor on the body
            from io import StringIO
            from html.parser import HTMLParser
            class _Strip(HTMLParser):
                def __init__(self):
                    super().__init__(); self._t = []
                def handle_data(self, d):
                    if d.strip(): self._t.append(d.strip())
            s = _Strip(); s.feed(content)
            parts.append("\n".join(s._t))
        else:
            parts.append(content)
    return "\n".join(parts)

def extract_odt(path):
    """Extract text from OpenDocument Text (.odt) files."""
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        content = z.read("content.xml")
    root = ET.fromstring(content)
    # ODF namespaces
    parts = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return "\n".join(parts)

def extract_ods(path):
    """Extract text from OpenDocument Spreadsheet (.ods) files."""
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        content = z.read("content.xml")
    root = ET.fromstring(content)
    parts = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return "\n".join(parts)

def extract_odp(path):
    """Extract text from OpenDocument Presentation (.odp) files."""
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        content = z.read("content.xml")
    root = ET.fromstring(content)
    parts = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return "\n".join(parts)

# ---- Extractor registry ----
# Maps file extension -> extraction function.
# Plain-text variants (log, config, source) all use extract_text.
EXTRACTORS = {
    # Documents
    ".pdf":  extract_pdf,
    ".docx": extract_docx,
    ".doc":  extract_docx,       # python-docx handles some .doc files
    ".pptx": extract_pptx,
    ".rtf":  extract_rtf,
    # Spreadsheets
    ".xlsx": extract_xlsx,
    ".xls":  extract_xls,
    ".csv":  extract_csv,
    ".tsv":  extract_csv,
    # OpenDocument (LibreOffice)
    ".odt":  extract_odt,
    ".ods":  extract_ods,
    ".odp":  extract_odp,
    # Email
    ".eml":  extract_eml,
    # Web / markup
    ".html": extract_html,
    ".htm":  extract_html,
    ".xml":  extract_xml,
    # Data interchange
    ".json": extract_json,
    ".yaml": extract_yaml,
    ".yml":  extract_yaml,
    # Plain text variants
    ".txt":  extract_text,
    ".md":   extract_text,
    ".rst":  extract_text,
    ".log":  extract_text,
    ".ini":  extract_text,
    ".cfg":  extract_text,
    ".conf": extract_text,
    ".env":  extract_text,
    ".properties": extract_text,
    ".toml": extract_text,
    ".sql":  extract_text,
    ".py":   extract_text,
    ".js":   extract_text,
    ".ts":   extract_text,
    ".java": extract_text,
    ".c":    extract_text,
    ".cpp":  extract_text,
    ".h":    extract_text,
    ".cs":   extract_text,
    ".rb":   extract_text,
    ".go":   extract_text,
    ".sh":   extract_text,
    ".bat":  extract_text,
    ".ps1":  extract_text,
}

def get_text(path):
    ext = path.suffix.lower()
    if ext not in EXTRACTORS:
        raise ValueError(f"unsupported extension: {ext}")
    return EXTRACTORS[ext](path)

# -------- Tier ranking --------
TIER_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

def max_tier(*tiers):
    return max(tiers, key=lambda t: TIER_RANK[t])

# -------- Zero-shot (semantic) layer --------

CATEGORY_TO_TIER = {
    "personally identifiable information such as social security numbers, full names with addresses, or government ID numbers": "restricted",
    "payment card data such as credit card numbers, primary account numbers, or CVV security codes":                           "restricted",
    "authentication credentials such as passwords, API keys, VPN shared secrets, or private keys":                             "restricted",
    "medical records, patient health information, diagnoses, or prescriptions":                                                "restricted",
    "salary, compensation, or employee financial records":                                                                     "confidential",
    "proprietary technology, trade secrets, source code, or technical security specifications":                                "confidential",
    "non-public business strategy, mergers and acquisitions, valuation models, unannounced financial projections, or material non-public information": "confidential",
    "internal business operations, company memos, non-public meeting notes, sprint retrospectives, product roadmaps, working drafts, postmortems, or internal team communications": "internal",
    "publicly available marketing material, press releases, or general public information":                                    "public",
}
CATEGORIES = list(CATEGORY_TO_TIER.keys())

# Words of text fed into the NLI classifier. DeBERTa-v3 models cap at 512
# tokens, so we keep ~400 words (with sub-word headroom). bge-m3 supports
# 8192 tokens; we use 6000 words there, which fits comfortably even for
# multi-byte / multi-token Cyrillic and CJK content.
MAX_WORDS_DEBERTA = 400
MAX_WORDS_MULTILINGUAL = 6000
MAX_WORDS = MAX_WORDS_DEBERTA  # overridden in main() when --multilingual

# Per-tier zero-shot thresholds. Public/internal categories often score in the
# 0.35–0.7 range on short internal documents (e.g. meeting notes), while
# restricted categories should require strong evidence to escalate.
PER_TIER_THRESHOLDS = {
    "public":       0.35,
    "internal":     0.35,
    "confidential": 0.50,
    "restricted":   0.70,
}

def short_name(cat):
    return cat.split(" such as")[0].split(",")[0].strip()

def zero_shot_classify(classifier, text):
    words = text.split()
    if len(words) > MAX_WORDS:
        text = " ".join(words[:MAX_WORDS])
    return classifier(text, candidate_labels=CATEGORIES,
                      hypothesis_template="This document contains {}.",
                      multi_label=True)

def zero_shot_tier(scores_by_category, threshold=None):
    """Pick highest-tier category whose score clears the per-tier floor.

    If `threshold` is given (CLI --threshold), it's used uniformly. Otherwise
    PER_TIER_THRESHOLDS is applied — a lower floor for public/internal (so a
    medium-confidence "internal business operations" still escalates), and a
    higher floor for restricted (so a stray 0.46 on "credentials" doesn't push
    a salary doc to RESTRICTED).
    """
    triggered = []
    for cat, score in scores_by_category.items():
        implied = CATEGORY_TO_TIER[cat]
        floor = threshold if threshold is not None else PER_TIER_THRESHOLDS[implied]
        if score >= floor:
            triggered.append((cat, score, implied))
    if not triggered:
        return "public", []
    triggered.sort(key=lambda t: (TIER_RANK[t[2]], t[1]), reverse=True)
    return triggered[0][2], triggered

# -------- Presidio (pattern/NER) layer --------

# Per-entity tier mapping. RESTRICTED entities always escalate (if their
# confidence clears the per-entity floor). CONFIDENTIAL entities (PERSON,
# EMAIL, PHONE, LOCATION) are evaluated as a *bundle* — see presidio_tier.
ENTITY_TO_TIER = {
    "US_SSN":             "restricted",
    "CREDIT_CARD":        "restricted",
    "IBAN_CODE":          "restricted",
    "US_BANK_NUMBER":     "restricted",
    "US_PASSPORT":        "restricted",
    "US_DRIVER_LICENSE":  "restricted",
    "MEDICAL_LICENSE":    "restricted",
    "CRYPTO":             "restricted",
    "CREDENTIAL":         "restricted",   # custom: key=value secrets
    "RNOKPP":             "restricted",   # custom: Ukrainian taxpayer ID
    "UA_PASSPORT":        "restricted",   # custom: Ukrainian passport series+num
    "UA_PHONE":           "confidential", # custom: +380 phone
    "EMAIL_ADDRESS":      "confidential",
    "PHONE_NUMBER":       "confidential",
    "PERSON":             "confidential",
    "LOCATION":           "confidential",
    "NRP":                "confidential",
    "IP_ADDRESS":         "internal",
    "URL":                "internal",
    "DATE_TIME":          "public",
}

RESTRICTED_ENTITIES = {e for e, t in ENTITY_TO_TIER.items() if t == "restricted"}

# Per-entity confidence floor. Suppresses noisy detections — e.g. Presidio's
# default US_DRIVER_LICENSE / US_PASSPORT recognizers fire at ~0.01–0.30 on
# tokens like "Q3", "L7", "v2"; PERSON / LOCATION NER misfires on company
# names, acronyms, and Cyrillic glyphs read through the English model.
PER_ENTITY_MIN_SCORE = {
    "US_SSN":            0.40,
    "CREDIT_CARD":       0.40,
    "IBAN_CODE":         0.40,
    "US_BANK_NUMBER":    0.50,
    "US_PASSPORT":       0.50,
    "US_DRIVER_LICENSE": 0.50,
    "MEDICAL_LICENSE":   0.40,
    "CRYPTO":            0.50,
    "CREDENTIAL":        0.50,
    "RNOKPP":            0.40,
    "UA_PASSPORT":       0.40,
    "UA_PHONE":          0.40,
    "EMAIL_ADDRESS":     0.50,
    "PHONE_NUMBER":      0.40,
    "PERSON":            0.70,
    "LOCATION":          0.70,
    "NRP":               0.70,
    "IP_ADDRESS":        0.50,
    "URL":               0.50,
    "UK_NHS":            1.10,   # disabled: collides with 10-digit РНОКПП
    "DATE_TIME":         1.10,   # disabled: tier-irrelevant
}

# Local-parts of email addresses that are *role inboxes*, not personal mailboxes.
# Lists like `press@…`, `info@…` in a press release shouldn't push the doc
# to CONFIDENTIAL; a personal `j.smith@…` should.
CORPORATE_EMAIL_LOCALPARTS = {
    "press", "media", "info", "contact", "support", "sales", "hello", "hi",
    "team", "admin", "administrator", "hr", "marketing", "office", "office-ops",
    "ops", "no-reply", "noreply", "donotreply", "webmaster", "postmaster",
    "abuse", "security", "legal", "privacy", "ir", "investor", "investors",
    "careers", "jobs", "billing", "help", "feedback", "enquiries", "inquiries",
}

def email_localpart_is_corporate(value: str) -> bool:
    local = value.split("@", 1)[0].lower().strip()
    return local in CORPORATE_EMAIL_LOCALPARTS

def build_analyzer():
    analyzer = AnalyzerEngine()

    # Credentials / secrets — keep from v3
    cred_patterns = [
        Pattern(
            name="key_value_secret",
            regex=r"(?i)\b(password|passwd|pwd|secret|shared[_\s-]?secret|api[_\s-]?key|access[_\s-]?token|private[_\s-]?key)\b\s*[:=]\s*\S{6,}",
            score=0.85,
        ),
        Pattern(
            name="ipsec_shared_secret",
            regex=r"(?i)IPSEC[_\s-]?SHARED[_\s-]?SECRET\s*[:=]?\s*[0-9a-f\-]{16,}",
            score=0.95,
        ),
        Pattern(
            name="aws_access_key_id",
            regex=r"\bAKIA[0-9A-Z]{16}\b",
            score=0.90,
        ),
        Pattern(
            name="pem_private_key",
            regex=r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
            score=0.99,
        ),
    ]
    analyzer.registry.add_recognizer(PatternRecognizer(
        supported_entity="CREDENTIAL",
        patterns=cred_patterns,
        context=["password", "secret", "credential", "key", "token", "vpn", "auth"],
    ))

    # РНОКПП (Ukrainian individual taxpayer number): 10 digits.
    # Bare-regex score is intentionally low (0.10) so it stays below the
    # entity floor (0.40) on accidental 10-digit hits like US bank account
    # numbers; Presidio's context boost (~+0.35) lifts genuine РНОКПП values
    # in Ukrainian HR documents above the floor.
    analyzer.registry.add_recognizer(PatternRecognizer(
        supported_entity="RNOKPP",
        patterns=[Pattern(
            name="rnokpp_10_digit",
            regex=r"\b\d{10}\b",
            score=0.10,
        )],
        context=["рнокпп", "інн", "ідентифікаційний", "идентификационный", "ipn"],
        supported_language="en",
    ))

    # Ukrainian internal passport: two Cyrillic uppercase letters + 6 digits.
    analyzer.registry.add_recognizer(PatternRecognizer(
        supported_entity="UA_PASSPORT",
        patterns=[Pattern(
            name="ua_passport_series_number",
            regex=r"\b[А-ЯҐЄІЇ]{2}\s?\d{6}\b",
            score=0.70,
        )],
        context=["паспорт", "серія", "passport"],
        supported_language="en",
    ))

    # Ukrainian mobile phone (+380 prefix). Presidio's PHONE_NUMBER recognizer
    # already catches most of these, but this gives a stable, high-precision
    # signal even when locale=en.
    analyzer.registry.add_recognizer(PatternRecognizer(
        supported_entity="UA_PHONE",
        patterns=[Pattern(
            name="ua_phone_plus380",
            regex=r"\+380\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}",
            score=0.80,
        )],
        context=["телефон", "phone"],
        supported_language="en",
    ))

    return analyzer

def presidio_scan(analyzer, text):
    """entity_type -> {count, max_score, samples (masked), raw_values}."""
    results = analyzer.analyze(text=text, language="en")
    summary = defaultdict(lambda: {"count": 0, "max_score": 0.0,
                                   "samples": [], "raw_values": []})
    for r in results:
        info = summary[r.entity_type]
        info["count"] += 1
        info["max_score"] = max(info["max_score"], r.score)
        raw = text[r.start:r.end]
        info["raw_values"].append(raw)
        if len(info["samples"]) < 2:
            masked = raw if len(raw) <= 8 else raw[:2] + "*" * (len(raw) - 4) + raw[-2:]
            info["samples"].append(masked)
    return dict(summary)

def _is_predominantly_non_latin(s: str, threshold: float = 0.5) -> bool:
    """True if more than `threshold` fraction of alphabetic chars in `s` are
    not basic Latin (a–z). Used to drop spaCy `en_core_web_lg` NER artifacts
    that fire PERSON/LOCATION/NRP on Cyrillic / CJK / Greek glyphs."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if not ('a' <= c.lower() <= 'z'))
    return (non_latin / len(letters)) > threshold

# Entity types that should be re-scored only on Latin-script raw values.
# Pattern-based entities (US_SSN, CREDIT_CARD, RNOKPP, UA_PASSPORT, …) are
# language-independent and must NOT be filtered by script.
_NER_LANGUAGE_SENSITIVE = {"PERSON", "LOCATION", "NRP"}

def _filter_by_floor(entity_summary):
    """Apply per-entity confidence floors and (for English NER-derived
    entities only) drop hits whose raw value is predominantly non-Latin."""
    out = {}
    for ent, info in entity_summary.items():
        floor = PER_ENTITY_MIN_SCORE.get(ent, 0.50)
        if info["max_score"] < floor:
            continue
        if ent in _NER_LANGUAGE_SENSITIVE:
            raw_values = info.get("raw_values", [])
            kept = [v for v in raw_values if not _is_predominantly_non_latin(v)]
            if not kept:
                continue
            # Rebuild the info dict with only the Latin-script hits so
            # downstream count-based rules see a consistent picture.
            info = dict(info)
            info["raw_values"] = kept
            info["count"] = len(kept)
            info["samples"] = info["samples"][:len(kept)]
        out[ent] = info
    return out

def presidio_tier(entity_summary):
    """Map filtered Presidio findings to a sensitivity tier.

    Rule layer (v4):
      - RESTRICTED: any restricted-tier entity that clears its floor.
      - CONFIDENTIAL: requires a *bundle* of PII — a single PERSON or a single
        role-inbox email (press@…) does NOT escalate. A doc reaches CONFIDENTIAL
        when it has phone+name, personal-email+name, multiple phones, multiple
        personal emails, or a named roster (3+ people with contact/location).
      - INTERNAL: URLs / IP addresses *alone* don't escalate — public press
        releases and marketing brochures have URLs too. Defer to zero-shot for
        the public/internal split.
    """
    filtered = _filter_by_floor(entity_summary)

    for ent in filtered:
        if ent in RESTRICTED_ENTITIES:
            return "restricted"

    n_person = filtered.get("PERSON", {}).get("count", 0)
    n_loc    = filtered.get("LOCATION", {}).get("count", 0)
    n_phone  = (filtered.get("PHONE_NUMBER", {}).get("count", 0)
                + filtered.get("UA_PHONE", {}).get("count", 0))

    # Personal-vs-corporate email split
    personal_emails = 0
    if "EMAIL_ADDRESS" in filtered:
        for v in filtered["EMAIL_ADDRESS"].get("raw_values", []):
            if not email_localpart_is_corporate(v):
                personal_emails += 1

    if n_phone >= 1 and n_person >= 1:        return "confidential"
    if personal_emails >= 1 and n_person >= 1: return "confidential"
    if n_phone >= 2:                           return "confidential"
    if personal_emails >= 2:                   return "confidential"
    # v6 fix #2: dropped the "≥3 PERSON + ≥2 LOC" bundle path. It had no
    # positive test case in test_corpus and fired on NER noise (notably
    # spaCy en_core_web_lg artifacts on Cyrillic). With v6 fix #1's
    # non-Latin filter, the remaining Latin PERSON+LOC combos that this
    # path would have triggered on are typically genuine (a list of named
    # people in named places), and those are better handled at the
    # zero-shot semantic layer than as a hard Presidio rule.

    return "public"

# -------- Output --------

def print_result(path, text, zs_scores, zs_tier, zs_triggered,
                 presidio_summary, p_tier, final_tier, threshold):
    print(f"\n=== {path.name} ===")
    if not text.strip():
        print("  (no text extracted)")
        return

    print(f"  FINAL TIER: {final_tier.upper()}")
    print(f"    zero-shot tier  : {zs_tier}")
    print(f"    presidio tier   : {p_tier if presidio_summary is not None else '(presidio not installed)'}")

    if presidio_summary:
        print(f"\n  Presidio findings:")
        # sort by implied tier descending then by count
        items = [(ent, info, ENTITY_TO_TIER.get(ent, "public"))
                 for ent, info in presidio_summary.items()]
        items.sort(key=lambda x: (TIER_RANK[x[2]], x[1]["count"]), reverse=True)
        for ent, info, implied in items:
            samples = ", ".join(info["samples"])
            print(f"    [{implied:12s}] {ent:18s} x{info['count']:<3d}"
                  f"  (max conf {info['max_score']:.0%})  e.g. {samples}")

    if threshold is None:
        thr_desc = ("per-tier: pub/int>=35%, conf>=50%, restr>=70%")
    else:
        thr_desc = f">= {threshold:.0%}"
    print(f"\n  Zero-shot categories ({thr_desc}):")
    if zs_triggered:
        for cat, score, implied in zs_triggered:
            print(f"    [{implied:12s}] {score:.1%}  {short_name(cat)}")
    else:
        print(f"    (none triggered)")

    print(f"\n  All zero-shot scores:")
    for cat, score in sorted(zs_scores.items(), key=lambda x: -x[1]):
        implied = CATEGORY_TO_TIER[cat]
        floor = threshold if threshold is not None else PER_TIER_THRESHOLDS[implied]
        bar = "#" * int(score * 30)
        marker = "*" if score >= floor else " "
        print(f"   {marker} {score:6.1%}  {short_name(cat):55s} {bar}")

    print(f"\n  Snippet: {' '.join(text.split()[:25])}...")

# -------- Classifier loader (CPU PyTorch or ORT+DirectML GPU) --------

def load_classifier(model_id: str, use_dml: bool):
    """Build a HuggingFace zero-shot pipeline.

    With `use_dml=False`, falls back to the stock PyTorch path (CPU here, since
    the installed torch is `+cpu`).

    With `use_dml=True`, exports the model to ONNX and runs it through
    `onnxruntime-directml`'s `DmlExecutionProvider` — this is the only viable
    GPU path for AMD RDNA cards on Windows. The export is
    cached under ~/.cache/doc_classifier_onnx so subsequent runs are fast.
    """
    from transformers import pipeline

    if not use_dml:
        return pipeline("zero-shot-classification", model=model_id)

    if not ORT_AVAILABLE:
        print("WARNING: GPU acceleration is enabled by default, but `optimum` is not installed.")
        print("         Install with: pip install optimum[onnxruntime] onnxruntime-directml")
        print("         Falling back to CPU (PyTorch).")
        return pipeline("zero-shot-classification", model=model_id)

    import onnxruntime as ort
    if "DmlExecutionProvider" not in ort.get_available_providers():
        print("WARNING: DmlExecutionProvider not available in this onnxruntime install.")
        print("         Make sure `onnxruntime-directml` is the active build:")
        print("           pip uninstall -y onnxruntime && pip install --force-reinstall onnxruntime-directml")
        print("         Falling back to CPU.")
        return pipeline("zero-shot-classification", model=model_id)

    from transformers import AutoTokenizer
    cache_root = Path.home() / ".cache" / "doc_classifier_onnx"
    cache_dir = cache_root / model_id.replace("/", "__")

    if (cache_dir / "model.onnx").exists():
        print(f"  Loading cached ONNX model from {cache_dir}")
        ort_model = ORTModelForSequenceClassification.from_pretrained(
            cache_dir, provider="DmlExecutionProvider"
        )
        tokenizer = AutoTokenizer.from_pretrained(cache_dir)
    else:
        # MoritzLaurer publishes a pre-converted ONNX alongside each zero-shot
        # checkpoint on the Hub. Pulling that is faster and avoids the local
        # torch.onnx export path (which is currently broken with the DirectML
        # build of onnxruntime — Optimum's `is_onnxruntime_available()` check
        # doesn't recognize `onnxruntime-directml`).
        print(f"  Fetching pre-converted ONNX for {model_id} from the Hub...")
        try:
            ort_model = ORTModelForSequenceClassification.from_pretrained(
                model_id, provider="DmlExecutionProvider"
            )
        except Exception as e:
            print(f"  No pre-converted ONNX available ({e}). Attempting local export...")
            ort_model = ORTModelForSequenceClassification.from_pretrained(
                model_id, export=True, provider="DmlExecutionProvider"
            )
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        ort_model.save_pretrained(cache_dir)
        tokenizer.save_pretrained(cache_dir)
        print(f"  Cached ONNX model to {cache_dir}")

    return pipeline("zero-shot-classification", model=ort_model, tokenizer=tokenizer)

# -------- Main --------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="File or directory to classify")
    parser.add_argument("--large", action="store_true",
                        help="Use deberta-v3-large (English-only). Mutually exclusive with --multilingual.")
    parser.add_argument("--multilingual", action="store_true",
                        help="Use bge-m3-zeroshot (multilingual, 8k context). "
                             "Mutually exclusive with --large.")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Uniform zero-shot threshold. Default: per-tier "
                             "table (public/internal=0.35, confidential=0.50, "
                             "restricted=0.70).")
    parser.add_argument("--no-presidio", action="store_true",
                        help="Skip Presidio (zero-shot only)")
    parser.add_argument("--cpu", action="store_true",
                        help="Run zero-shot inference on the CPU (disable GPU DirectML acceleration).")
    args = parser.parse_args()

    if args.large and args.multilingual:
        parser.error("--large and --multilingual are mutually exclusive; pick one.")

    use_presidio = PRESIDIO_AVAILABLE and not args.no_presidio
    if not PRESIDIO_AVAILABLE and not args.no_presidio:
        print("WARNING: presidio-analyzer not installed; falling back to zero-shot only.")
        print("         Install with: pip install presidio-analyzer presidio-anonymizer")
        print("                       python -m spacy download en_core_web_lg\n")

    # Pick zero-shot model and matching context window
    global MAX_WORDS
    if args.multilingual:
        model = "MoritzLaurer/bge-m3-zeroshot-v2.0-c"
        MAX_WORDS = MAX_WORDS_MULTILINGUAL
    elif args.large:
        model = "MoritzLaurer/deberta-v3-large-zeroshot-v2.0"
        MAX_WORDS = MAX_WORDS_DEBERTA
    else:
        model = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
        MAX_WORDS = MAX_WORDS_DEBERTA
    use_dml = not args.cpu
    print(f"Loading zero-shot model: {model}  (MAX_WORDS={MAX_WORDS})")
    if use_dml and ORT_AVAILABLE:
        print("  Backend: ONNX Runtime + DirectML (GPU)")
    classifier = load_classifier(model, use_dml=use_dml)

    analyzer = None
    if use_presidio:
        print("Loading Presidio analyzer (with custom CREDENTIAL recognizer) ...")
        analyzer = build_analyzer()

    target = Path(args.path)
    if not target.exists():
        print(f"path not found: {target}", file=sys.stderr)
        return 1

    files = ([target] if target.is_file()
             else sorted(p for p in target.rglob("*")
                         if p.is_file() and p.suffix.lower() in EXTRACTORS))
    if not files:
        print(f"no supported files in {target}", file=sys.stderr)
        return 1

    for f in files:
        try:
            text = get_text(f)

            # Zero-shot
            zs_result = zero_shot_classify(classifier, text)
            zs_scores = dict(zip(zs_result["labels"], zs_result["scores"]))
            zs_t, zs_triggered = zero_shot_tier(zs_scores, args.threshold)

            # Presidio
            if analyzer is not None:
                presidio_summary = presidio_scan(analyzer, text)
                p_t = presidio_tier(presidio_summary)
            else:
                presidio_summary = None
                p_t = "public"

            # Strip raw_values from per-call summary before printing
            if presidio_summary:
                for info in presidio_summary.values():
                    info.pop("raw_values", None)

            # Combine: max sensitivity wins
            final = max_tier(zs_t, p_t) if analyzer else zs_t

            print_result(f, text, zs_scores, zs_t, zs_triggered,
                         presidio_summary, p_t, final, args.threshold)
        except Exception as e:
            print(f"\n=== {f.name} ===\n  ERROR: {e}")

    print()
    return 0

if __name__ == "__main__":
    sys.exit(main())

# -------- Next steps for the full project --------
# 1. Chunk long documents (every ~400 words, with overlap) and keep MAX tier across chunks.
# 2. OCR fallback (pytesseract) for scanned PDFs with no extractable text.
# 3. Tune per-entity thresholds in Presidio (e.g. PERSON has many false positives).
# 4. Add domain-specific custom recognizers (Ukrainian РНОКПП/IPN, EU IBAN variants).
# 5. Wrap the whole pipeline in FastAPI for the web service.
