"""Phase 14 — in-browser text preview.

Decrypts a file's bytes via the existing `files.stream_download` path,
extracts a textual view, and returns the first ~100 KB of UTF-8 text.

Supported formats (text only — no binary embedding):
  * Plain text variants (txt, md, log, csv, tsv, json, yaml, html, sql,
    ini, cfg, conf, env, properties, toml, rst)
  * PDF, DOCX — the classifier's full extraction (`classifier_core.pdf_text` /
    `docx_text`): everything in the file, including text a reader would not see

Both extractors accept file-like objects, so the plaintext never touches
disk. Anything else returns `UnsupportedPreviewError` and the SPA shows
"preview not available — download to view".
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterable
from dataclasses import dataclass

from app.models.file import File
from app.models.user import User
from app.services import audit, files

# Cap the response at 100 KB of *extracted text*. PDF/DOCX inputs can be
# much larger on disk — the cap protects the SPA from rendering a 50 MB
# `<pre>` block and the network from shipping it.
PREVIEW_BYTE_LIMIT = 100 * 1024

# Mime types and extensions we treat as plain text. We check mime first
# (what the upload told us) and fall back to extension because users often
# upload .csv with `application/octet-stream`.
_PLAIN_TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "text/html",
    "text/xml",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "text/yaml",
    "application/yaml",
    "application/toml",
    "text/x-log",
    "application/x-sh",
}
_PLAIN_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".xml",
    ".sql",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".toml",
    ".sh",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
}


class UnsupportedPreviewError(ValueError):
    """No text extractor for this file (binary / image / archive)."""


class PreviewExtractionError(RuntimeError):
    """Extractor crashed mid-flight (corrupt PDF, password-protected DOCX, etc.)."""


@dataclass
class PreviewPayload:
    text: str
    truncated: bool
    extractor: str  # "text" | "pdf" | "docx"
    original_bytes: int  # full plaintext length before truncation


def _ext_of(file_record: File) -> str:
    return os.path.splitext(file_record.original_filename or "")[1].lower()


def _is_plain_text(file_record: File) -> bool:
    mime = (file_record.mime_type or "").lower()
    if mime in _PLAIN_TEXT_MIMES:
        return True
    if mime.startswith("text/"):
        return True
    return _ext_of(file_record) in _PLAIN_TEXT_EXTENSIONS


def _is_pdf(file_record: File) -> bool:
    return (file_record.mime_type or "").lower() == "application/pdf" or _ext_of(file_record) == ".pdf"


def _is_docx(file_record: File) -> bool:
    mime = (file_record.mime_type or "").lower()
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return True
    return _ext_of(file_record) in {".docx", ".doc"}


def _collect_plaintext(chunks: Iterable[bytes]) -> bytes:
    return b"".join(chunks)


def _extract_pdf(blob: bytes) -> str:
    from app.classifier_core.pdf_text import pdf_views

    # Same extractor as the classifier, so the preview shows what it saw. The cap stops
    # a 1000-page PDF early when the SPA only renders 100 KB anyway.
    return pdf_views(io.BytesIO(blob), max_chars=PREVIEW_BYTE_LIMIT * 4).full


def _extract_docx(blob: bytes) -> str:
    from app.classifier_core.docx_text import docx_views

    return docx_views(io.BytesIO(blob)).full


def _extract_plain_text(blob: bytes) -> str:
    # Files may be uploaded in any encoding; decoding errors are replaced
    # rather than raised so the preview always renders something.
    return blob.decode("utf-8", errors="replace")


def build_preview(file_record: File, *, actor: User | None) -> PreviewPayload:
    """Extract a preview text from *file_record*.

    Raises:
      UnsupportedPreviewError — no extractor for this file.
      PreviewExtractionError — extractor crashed.
    """
    if _is_plain_text(file_record):
        extractor = "text"
    elif _is_pdf(file_record):
        extractor = "pdf"
    elif _is_docx(file_record):
        extractor = "docx"
    else:
        raise UnsupportedPreviewError(
            f"No preview extractor for mime={file_record.mime_type!r} ext={_ext_of(file_record)!r}"
        )

    # Reuse the same decrypt path the download endpoint uses, but suppress
    # its audit row — we emit `file.previewed` below instead so the audit
    # log can distinguish "downloaded the bytes" from "read the text".
    chunks = files.stream_download(file_record, actor=actor, emit_audit=False)
    blob = _collect_plaintext(chunks)

    try:
        if extractor == "text":
            text = _extract_plain_text(blob)
        elif extractor == "pdf":
            text = _extract_pdf(blob)
        else:  # docx
            text = _extract_docx(blob)
    except Exception as exc:  # noqa: BLE001 — pdfplumber/docx raise varied types
        raise PreviewExtractionError(str(exc)) from exc

    encoded = text.encode("utf-8", errors="replace")
    truncated = len(encoded) > PREVIEW_BYTE_LIMIT
    if truncated:
        # Truncate at byte boundary; decode with `replace` so we never split
        # a multi-byte rune.
        cut = encoded[:PREVIEW_BYTE_LIMIT].decode("utf-8", errors="replace")
        text = cut

    audit.record(
        "file.previewed",
        actor=actor,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "filename": file_record.original_filename,
            "size_bytes": file_record.size_bytes,
            "extractor": extractor,
            "truncated": truncated,
            "preview_bytes": len(text.encode("utf-8", errors="replace")),
        },
    )

    return PreviewPayload(
        text=text,
        truncated=truncated,
        extractor=extractor,
        original_bytes=len(encoded),
    )


# Raw PDF/DOCX for rendering in the browser (pdf.js / docx-preview). Bigger files are
# better downloaded than parsed in a tab.
DOCUMENT_PREVIEW_LIMIT = 25 * 1024 * 1024
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class PreviewTooLargeError(ValueError):
    """File is over DOCUMENT_PREVIEW_LIMIT."""


def document_bytes(file_record: File, *, actor: User | None) -> tuple[bytes, str]:
    """Decrypted PDF/DOCX bytes + mime type for in-browser rendering.

    Raises UnsupportedPreviewError (not PDF/DOCX; legacy .doc included) or
    PreviewTooLargeError. Audits `file.previewed` with mode=document.
    """
    if _is_pdf(file_record):
        mime = "application/pdf"
    elif _is_docx(file_record) and _ext_of(file_record) != ".doc":
        mime = DOCX_MIME
    else:
        raise UnsupportedPreviewError("Document preview is only available for PDF and DOCX.")
    if file_record.size_bytes > DOCUMENT_PREVIEW_LIMIT:
        raise PreviewTooLargeError(f"{file_record.size_bytes} bytes")
    blob = _collect_plaintext(files.stream_download(file_record, actor=actor, emit_audit=False))
    audit.record(
        "file.previewed",
        actor=actor,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "filename": file_record.original_filename,
            "size_bytes": file_record.size_bytes,
            "mode": "document",
        },
    )
    return blob, mime
