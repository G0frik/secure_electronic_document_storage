"""On-disk cache of engine outputs keyed by (sha256(text), engine, model, prompt_version)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(text: str, engine: str, model: str, prompt_version: str = "") -> str:
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashlib.sha256(
        json.dumps([text_hash, engine, model, prompt_version]).encode("utf-8")
    ).hexdigest()


class Cache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self.path(key)
        if not p.exists():
            return None
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return data

    def put(self, key: str, value: dict[str, Any]) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
