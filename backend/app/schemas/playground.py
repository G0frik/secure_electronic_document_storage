"""Pydantic schemas for /api/admin/playground/*."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Defense = Literal["D1", "D2", "D4", "D6"]

MAX_ROWS = 12
MAX_TEXT_CHARS = 200_000
MAX_PROMPT_CHARS = 8_000
MAX_PAYLOAD_CHARS = 2_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupSpec(_Strict):
    """One grid row: a classifier setup. `model` is an NLI config id or an LLM label."""

    label: str = Field(default="", max_length=120)
    engine: Literal["nli", "llm"]
    model: str = Field(min_length=1, max_length=120)
    prompt: str = Field(default="classify_v1", max_length=64)
    prompt_text: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int = Field(default=256, ge=16, le=4096)
    thinking: bool = False
    presidio: bool = True
    defenses: list[Defense] = Field(default_factory=list)
    detector: Literal["pg2", "protectai"] = "pg2"
    expected_tier: str | None = Field(default=None, max_length=16)  # presets: the research result

    @field_validator("prompt_text")
    @classmethod
    def _has_slot(cls, v: str | None) -> str | None:
        if v is not None and "{document}" not in v:
            raise ValueError("the prompt must contain {document}")
        return v

    @field_validator("defenses")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class AttackIn(_Strict):
    attack: Literal["none", "A1", "A2", "A3", "A4", "A5", "A6", "A7"] = "none"
    payload_lang: Literal["en", "uk"] = "en"
    placement: Literal["start", "end"] = "start"
    carrier: str = Field(default="", max_length=32)
    a3_payload: Literal["A1", "A2"] = "A1"
    payload: str | None = Field(default=None, max_length=MAX_PAYLOAD_CHARS)
    output_format: Literal["txt", "docx", "pdf"] = "txt"


class InputIn(_Strict):
    kind: Literal["text", "file", "corpus"]
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    text_format: Literal["txt", "docx", "pdf"] = "docx"
    lang: Literal["en", "uk"] = "en"
    file_id: uuid.UUID | None = None
    corpus_ref: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _one_source(self) -> InputIn:
        need = {"text": self.text, "file": self.file_id, "corpus": self.corpus_ref}[self.kind]
        if not need:
            raise ValueError(f"input kind {self.kind!r} needs its value")
        return self


class DocumentRequest(_Strict):
    input: InputIn
    attack: AttackIn = Field(default_factory=AttackIn)


class RunCreateRequest(DocumentRequest):
    setups: list[SetupSpec] = Field(min_length=1, max_length=MAX_ROWS)
    explain: bool = False
    preset: str | None = Field(default=None, max_length=64)


class SetupSaveRequest(_Strict):
    name: str = Field(min_length=1, max_length=120)
    rows: list[SetupSpec] = Field(min_length=1, max_length=MAX_ROWS)
