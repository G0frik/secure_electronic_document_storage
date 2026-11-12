"""Run manifest: everything needed to reproduce a run."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("torch", "transformers", "presidio-analyzer", "pdfplumber", "python-docx"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "missing"
    return out


def write_manifest(run_dir: Path, **fields: Any) -> Path:
    # .git is not mounted into the container, so the commit comes from the caller (Makefile).
    data = {"git_commit": os.environ.get("GIT_COMMIT", "unknown"), "versions": _versions(), **fields}
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
