"""Admin playground: classify one (optionally attacked) document with several setups side by side.

Runs only with PLAYGROUND=1. Never changes a file, classification row or access decision of the
service: a run keeps its own encrypted copies of the input and attacked document and its own results.
LLMs are served by a llama-server router on the host (one model loaded at a time); NLI runs on the
host NLI server (GPU). Only one of them holds the GPU at a time: the task frees the other first.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import or_, select

from app.classifier_core import zero_shot
from app.classifier_core.llm import CATEGORY_NAMES, LLM_MAX_WORDS, PROMPTS_DIR, _truncate
from app.config import settings
from app.extensions import db
from app.logging_config import get_logger
from app.models.file import File
from app.models.playground import PlaygroundDocument, PlaygroundRow, PlaygroundRun
from app.models.user import User
from app.schemas.playground import DocumentRequest, InputIn, RunCreateRequest, SetupSpec
from app.services import audit, crypto, files, policy, storage
from app.services import playground_attacks as attacks

log = get_logger(__name__)

# NLI configs as named in the research (research/engines.py): model, words per window, windows on/off
NLI_CONFIGS: dict[str, dict[str, Any]] = {
    "nli_en": {"model": zero_shot.LARGE_MODEL, "max_words": zero_shot.MAX_WORDS_DEBERTA,
               "windows": True, "label": "DeBERTa-v3 large, 400-word windows"},
    "nli_en_trunc": {"model": zero_shot.LARGE_MODEL, "max_words": zero_shot.MAX_WORDS_DEBERTA,
                     "windows": False, "label": "DeBERTa-v3 large, first 400 words only (before windows)"},
    "nli_ml": {"model": zero_shot.MULTILINGUAL_MODEL, "max_words": zero_shot.MAX_WORDS_MULTILINGUAL,
               "windows": False, "label": "bge-m3, one pass up to 6000 words"},
    "nli_ml_w": {"model": zero_shot.MULTILINGUAL_MODEL,
                 "max_words": zero_shot.WINDOW_WORDS_MULTILINGUAL, "windows": True,
                 "label": "bge-m3, 400-word windows (service setting)"},
}  # fmt: skip
PROMPTS = ("classify_v1", "classify_v1_uk", "classify_hardened_v1")
EXPLAIN_PROMPT = "classify_explain_v1"
RESEARCH_DEFAULTS = {"seed": 42, "temperature": 0.0, "top_p": None, "max_tokens": 256,
                     "thinking": False, "prompt": "classify_v1", "presidio": True}  # fmt: skip
LLM_TIMEOUT = 300  # first request to a model includes loading it
DOC_TYPES = {".txt", ".md", ".docx", ".pdf"}


class PlaygroundError(ValueError):
    """Shown to the admin as a 400."""


# ---------- catalog ----------


def llm_models() -> tuple[list[dict[str, str]], str]:
    """Models the host llama-server router offers, with load state; and an error if unreachable."""
    try:
        r = requests.get(f"{settings.llm_base_url.rstrip('/')}/models", timeout=5)
        r.raise_for_status()
        data = r.json()["data"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        return [], f"LLM server not reachable ({type(exc).__name__}); start it with make playground"
    return [{"id": m["id"], "status": m.get("status", {}).get("value", "")} for m in data], ""


def nli_server_ok() -> bool:
    try:
        return requests.get(settings.playground_nli_url, timeout=5).ok
    except requests.RequestException:
        return False


def catalog() -> dict[str, Any]:
    models, llm_error = llm_models()
    return {
        "nli": [{"id": k, "label": v["label"]} for k, v in NLI_CONFIGS.items()],
        "nli_server": nli_server_ok(),
        "llm": models,
        "llm_error": llm_error,
        "prompts": {p: (PROMPTS_DIR / f"{p}.txt").read_text(encoding="utf-8") for p in PROMPTS},
        "explain_prompt": EXPLAIN_PROMPT,
        "defenses": {
            "D1": "Hardened prompt (LLM only)",
            "D2": "Classify visible and full text, keep the higher tier",
            "D4": "Injection detector: flagged → RESTRICTED",
            "D6": "Presidio also scans a copy with look-alikes folded back",
        },
        "detectors": ["pg2", "protectai"],
        "defaults": RESEARCH_DEFAULTS,
        "attacks": attacks.catalog(),
        "corpus": bool(attacks.corpus_dirs()),
        "presets": presets(),
    }


PRESETS_FILE = Path(__file__).with_name("playground_presets.json")


def presets() -> list[dict[str, Any]]:
    """Ready-made runs (case examples): only those whose corpus document and research file exist."""
    try:
        raw = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("playground.presets_unreadable", error=str(exc))
        return []
    out = []
    for p in raw:
        try:
            out.extend(_preset(p))
        except (KeyError, TypeError, ValueError) as exc:  # pydantic errors are ValueErrors
            log.warning("playground.preset_skipped", preset=p.get("id"), error=str(exc))
    return out


def _preset(p: dict[str, Any]) -> list[dict[str, Any]]:
    """The preset ready for the page, or nothing when its files are not on this machine."""
    from app.schemas.playground import AttackIn

    entry = next((e for e in attacks.corpus_index()
                  if e["pair_id"] == p["pair_id"] and e["lang"] == p["lang"]), None)  # fmt: skip
    attack = AttackIn.model_validate(p["attack"])
    spec = _spec(DocumentRequest(input=InputIn(kind="corpus", corpus_ref="x"), attack=attack),
                 p["lang"])  # fmt: skip
    if entry is None or attacks.research_variant(p["pair_id"], p["lang"], spec) is None:
        return []
    return [{
        "id": p["id"], "title": p["title"], "summary": p["summary"], "explain": p["explain"],
        "corpus_ref": entry["ref"], "attack": attack.model_dump(),
        "setups": [SetupSpec.model_validate(s).model_dump() for s in p["setups"]],
    }]  # fmt: skip


# ---------- documents ----------


def _store(run: PlaygroundRun, kind: str, doc: attacks.Doc) -> PlaygroundDocument:
    blob = crypto.encrypt_file(doc.data)
    key = f"playground/{run.id}/{kind}"
    storage.put(key, io.BytesIO(blob.ciphertext), len(blob.ciphertext), "application/octet-stream")
    row = PlaygroundDocument(
        run_id=run.id, kind=kind, filename=doc.filename, content_type=doc.content_type,
        size_bytes=len(doc.data), storage_key=key, wrapped_dek=blob.wrapped_dek,
        nonce=blob.nonce, auth_tag=blob.auth_tag, kek_version=blob.kek_version,
    )  # fmt: skip
    db.session.add(row)
    return row


def _commit_with_documents(run: PlaygroundRun, docs: list[tuple[str, attacks.Doc]]) -> None:
    """Upload the run's documents and commit; on failure no object is left without its row."""
    stored: list[str] = []
    try:
        for kind, doc in docs:
            stored.append(_store(run, kind, doc).storage_key)
        db.session.commit()
    except Exception:
        db.session.rollback()
        for key in stored:
            storage.delete(key)
        raise


def load(doc: PlaygroundDocument) -> attacks.Doc:
    response = storage.get(doc.storage_key)
    try:
        ciphertext = b"".join(response.stream(64 * 1024))
    finally:
        response.close()
        response.release_conn()
    plain = crypto.decrypt_file(
        ciphertext=ciphertext, wrapped_dek=doc.wrapped_dek, nonce=doc.nonce,
        auth_tag=doc.auth_tag, kek_version=doc.kek_version,
    )  # fmt: skip
    return attacks.Doc(plain, doc.filename, doc.content_type)


def views(doc: attacks.Doc) -> dict[str, str]:
    from app.classifier_core.extract import get_views_bytes

    try:
        v = get_views_bytes(doc.data, doc.filename)
    except Exception as exc:  # noqa: BLE001 — pdf/docx parsers raise varied types
        raise PlaygroundError(f"Could not read {doc.filename}: {type(exc).__name__}") from exc
    return {"full": v.full, "visible": v.visible}


def resolve_input(spec: InputIn, actor: User) -> tuple[attacks.Doc, dict[str, Any]]:
    """The input document and what is known about it (language, corpus pair, title, ref)."""
    if spec.kind == "text":
        doc = attacks.render_text(spec.text or "", spec.text_format)
        return doc, {"lang": spec.lang, "name": f"Typed text ({spec.text_format})", "ref": None}
    if spec.kind == "file":
        record = files.get_by_id(spec.file_id) if spec.file_id else None
        if record is None:
            raise PlaygroundError("File not found.")
        ext = "." + record.original_filename.rsplit(".", 1)[-1].lower()
        if ext not in DOC_TYPES:
            raise PlaygroundError("The playground takes PDF, DOCX, TXT and MD files.")
        decision = policy.can_user_access(actor, record)  # recorded like any download
        if not decision.allowed:
            raise PlaygroundError(f"Access denied by policy ({decision.reason}).")
        data = b"".join(files.stream_download(record, actor=actor))
        audit.record(
            "playground.file_used", actor=actor, target_type="file", target_id=record.id,
            metadata={"filename": record.original_filename, "owner_id": str(record.owner_id)},
        )  # fmt: skip
        ctype = attacks.CONTENT_TYPES.get(ext.lstrip("."), record.mime_type)
        doc = attacks.Doc(data, record.original_filename, ctype)
        return doc, {"lang": spec.lang, "name": record.original_filename, "ref": str(record.id)}
    try:
        doc, entry = attacks.corpus_doc(spec.corpus_ref or "")
    except attacks.AttackError as exc:
        raise PlaygroundError(str(exc)) from exc
    return doc, {
        "lang": entry["lang"], "name": doc.filename, "ref": entry["ref"],
        "pair_id": entry["pair_id"], "tier": entry["tier"],
    }  # fmt: skip


def _spec(req: DocumentRequest, lang: str) -> attacks.AttackSpec:
    a = req.attack
    return attacks.AttackSpec(
        attack=a.attack, lang=lang, payload_lang=a.payload_lang, placement=a.placement,
        carrier=a.carrier, a3_payload=a.a3_payload, payload=a.payload,
        output_format=a.output_format,
    )  # fmt: skip


def build(
    req: DocumentRequest, actor: User
) -> tuple[attacks.Doc, attacks.Doc, str, dict[str, Any]]:
    """(input, attacked, how the attacked one was made, input info)."""
    doc, info = resolve_input(req.input, actor)
    spec = _spec(req, info["lang"])
    if "pair_id" in info:
        variant = attacks.research_variant(info["pair_id"], info["lang"], spec)
        if variant is not None:
            fmt = variant.suffix.lstrip(".")
            return doc, attacks.Doc(variant.read_bytes(), variant.name,
                                    attacks.CONTENT_TYPES[fmt]), "research-variant", info  # fmt: skip
    if spec.attack == "none":
        return doc, doc, "none", info
    text = views(doc)["full"]
    if not text.strip():
        raise PlaygroundError("No text could be extracted from the input.")
    form = str(info.get("pair_id", "")).startswith("res_id_form_")
    try:
        return doc, attacks.apply(doc, text, spec, form=form), "adapter", info
    except attacks.AttackError as exc:
        raise PlaygroundError(str(exc)) from exc


# ---------- runs ----------


def create_run(req: RunCreateRequest, actor: User) -> PlaygroundRun:
    for s in req.setups:
        check_setup(s)
    doc, attacked, source, info = build(req, actor)
    title = info["name"] if req.attack.attack == "none" else f"{info['name']} · {req.attack.attack}"
    run = PlaygroundRun(
        id=uuid.uuid4(), created_by_id=actor.id, title=title[:300], input_kind=req.input.kind,
        input_ref=info.get("ref"), attack=req.attack.model_dump(), attack_source=source,
        explain=req.explain, preset=req.preset, status="pending",
    )  # fmt: skip
    db.session.add(run)
    for i, s in enumerate(req.setups):
        db.session.add(PlaygroundRow(run_id=run.id, position=i, setup=s.model_dump(),
                                     status="pending"))  # fmt: skip
    _commit_with_documents(run, [("input", doc), ("attacked", attacked)])
    audit.record("playground.run_created", actor=actor, target_type="playground_run",
                 target_id=run.id, metadata={"title": run.title, "rows": len(req.setups)})  # fmt: skip
    return run


def rerun(run: PlaygroundRun, actor: User) -> PlaygroundRun:
    """Same documents and setups as a new run (the attacked document is copied, not rebuilt)."""
    new = PlaygroundRun(
        id=uuid.uuid4(), created_by_id=actor.id, title=run.title, input_kind=run.input_kind,
        input_ref=run.input_ref, attack=run.attack, attack_source=run.attack_source,
        explain=run.explain, preset=run.preset, status="pending",
    )  # fmt: skip
    docs = [(d.kind, load(d)) for d in run.documents]
    db.session.add(new)
    for r in run.rows:
        db.session.add(PlaygroundRow(run_id=new.id, position=r.position, setup=r.setup,
                                     status="pending"))  # fmt: skip
    _commit_with_documents(new, docs)
    audit.record("playground.run_created", actor=actor, target_type="playground_run",
                 target_id=new.id, metadata={"title": new.title, "rerun_of": str(run.id)})  # fmt: skip
    return new


def delete_run(run: PlaygroundRun, actor: User) -> None:
    keys = [d.storage_key for d in run.documents]
    title, run_id = run.title, run.id
    db.session.delete(run)
    db.session.commit()
    for key in keys:
        storage.delete(key)
    audit.record("playground.run_deleted", actor=actor, target_type="playground_run",
                 target_id=run_id, metadata={"title": title})  # fmt: skip


def get_run(run_id: uuid.UUID) -> PlaygroundRun | None:
    return db.session.get(PlaygroundRun, run_id)


def list_runs(limit: int = 50, offset: int = 0) -> list[PlaygroundRun]:
    stmt = (
        select(PlaygroundRun).order_by(PlaygroundRun.created_at.desc()).limit(limit).offset(offset)
    )
    return list(db.session.scalars(stmt))


def list_files(query: str, limit: int = 50) -> list[tuple[File, str]]:
    """Any user's files of a type the playground takes, newest first, with the owner's e-mail."""
    stmt = (
        select(File, User.email)
        .join(User, User.id == File.owner_id)
        .where(File.deleted_at.is_(None))
        .where(or_(*(File.original_filename.ilike(f"%{ext}") for ext in DOC_TYPES)))
        .order_by(File.uploaded_at.desc())
        .limit(limit)
    )
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(File.original_filename.ilike(f"%{escaped}%", escape="\\"))
    return [(f, e) for f, e in db.session.execute(stmt).all()]


# ---------- classification (worker) ----------


def check_setup(s: SetupSpec) -> None:
    if s.engine == "nli" and s.model not in NLI_CONFIGS:
        raise PlaygroundError(f"Unknown NLI config {s.model!r}.")
    if s.engine == "llm":
        if s.prompt not in PROMPTS:
            raise PlaygroundError(f"Unknown prompt {s.prompt!r}.")
        if not s.model.replace("-", "").replace(".", "").replace("_", "").isalnum():
            raise PlaygroundError("Invalid model name.")


def config_for(s: SetupSpec) -> Any:
    from app.classifier_core.pipeline import ClassifierConfig

    base: dict[str, Any] = {
        "presidio": s.presidio, "defenses": frozenset(s.defenses), "detector": s.detector,
        "llm_base_url": settings.llm_base_url, "llm_timeout": LLM_TIMEOUT,
    }  # fmt: skip
    if s.engine == "nli":
        c = NLI_CONFIGS[s.model]
        return ClassifierConfig(engine="nli", nli_model=c["model"], nli_max_words=c["max_words"],
                                nli_windows=c["windows"], nli_url=settings.playground_nli_url,
                                **base)  # fmt: skip
    return ClassifierConfig(
        engine="llm", llm_model=s.model, llm_prompt=s.prompt, llm_prompt_text=s.prompt_text,
        seed=s.seed, temperature=s.temperature, top_p=s.top_p, max_tokens=s.max_tokens,
        thinking=s.thinking, **base,
    )  # fmt: skip


def _free_gpu_for(engine: str) -> None:
    """Unload the other engine's models so the next one fits in VRAM (12 GB)."""
    try:
        if engine == "nli":
            for m, status in [(m["id"], m["status"]) for m in llm_models()[0]]:
                if status == "loaded":
                    requests.post(f"{settings.llm_base_url.rstrip('/')}/models/unload",
                                  json={"model": m}, timeout=60)  # fmt: skip
        else:
            requests.post(f"{settings.playground_nli_url.rstrip('/')}/unload", timeout=60)
    except requests.RequestException as exc:  # the next request reports the real problem
        log.warning("playground.free_gpu_failed", engine=engine, error=str(exc))


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {  # order matters: llama.cpp generates the properties in this order
        "tier": {"type": "string", "enum": ["public", "internal", "confidential", "restricted"]},
        "reason": {"type": "string", "maxLength": 300},
        "categories": {"type": "array", "items": {"type": "string", "enum": CATEGORY_NAMES},
                       "maxItems": len(CATEGORY_NAMES)},
    },
    "required": ["tier", "reason", "categories"],
    "additionalProperties": False,
}  # fmt: skip


def explain(s: SetupSpec, text: str) -> dict[str, str]:
    """The model's own one-sentence reason, from a separate call (as research/explain.py)."""
    doc, _ = _truncate(text, LLM_MAX_WORDS)
    prompt = (PROMPTS_DIR / f"{EXPLAIN_PROMPT}.txt").read_text(encoding="utf-8")
    body: dict[str, Any] = {
        "model": s.model,
        "messages": [{"role": "user", "content": prompt.replace("{document}", doc)}],
        "temperature": s.temperature, "max_tokens": max(s.max_tokens, 256), "seed": s.seed,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "classification", "schema": EXPLAIN_SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }  # fmt: skip
    r = requests.post(f"{settings.llm_base_url.rstrip('/')}/v1/chat/completions", json=body,
                      timeout=LLM_TIMEOUT)  # fmt: skip
    r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    return {"tier": out["tier"], "reason": out["reason"]}


def _order(rows: list[PlaygroundRow]) -> list[PlaygroundRow]:
    """NLI rows first, then LLM rows grouped by model: as few model switches as possible."""
    return sorted(rows, key=lambda r: (r.setup["engine"] == "llm", r.setup["model"], r.position))


def execute(run_id: uuid.UUID) -> str:
    """Worker body: classify the attacked document with every pending row's setup."""
    from app.classifier_core.docx_text import TextViews

    run = get_run(run_id)
    if run is None:
        return "missing"
    run.status = "running"
    db.session.commit()
    try:
        attacked = next(d for d in run.documents if d.kind == "attacked")
        v = views(load(attacked))
    except Exception as exc:  # noqa: BLE001 — record it on the run instead of retrying
        log.warning("playground.run_failed", run_id=str(run_id), error=str(exc))
        for r in run.rows:
            if r.status == "pending":
                r.status, r.error = "failed", f"document unreadable: {exc}"[:2000]
        run.status = "failed"
        db.session.commit()
        return run.status
    text_views = TextViews(full=v["full"], visible=v["visible"])
    try:
        _execute_rows(run, text_views)
    except Exception as exc:  # noqa: BLE001 — never leave a run "running" (e.g. deleted mid-run)
        db.session.rollback()
        log.warning("playground.run_aborted", run_id=str(run_id), error=str(exc))
        run = get_run(run_id)
        if run is None:
            return "deleted"
        for r in run.rows:
            if r.status in ("pending", "running"):
                r.status, r.error = "failed", f"run aborted: {type(exc).__name__}: {exc}"[:2000]
        run.status = "failed"
        db.session.commit()
        return run.status
    run.status = "failed" if all(r.status == "failed" for r in run.rows) else "done"
    db.session.commit()
    return run.status


def _execute_rows(run: PlaygroundRun, text_views: Any) -> None:
    from app.classifier_core.pipeline import classify, classify_views

    current = ""
    for row in _order([r for r in run.rows if r.status == "pending"]):
        setup = SetupSpec.model_validate(row.setup)
        gpu = "nli" if setup.engine == "nli" else f"llm:{setup.model}"
        if gpu != current:
            _free_gpu_for(setup.engine)
            current = gpu
        row.status, row.started_at = "running", datetime.now(UTC)
        db.session.commit()
        t0 = time.perf_counter()
        cfg = config_for(setup)
        trace: list[dict[str, Any]] = []  # LLM rows: raw answer + reasoning per classified view
        try:
            fn = partial(classify, cfg=cfg, trace=trace)
            res = classify_views(text_views, classifier_fn=fn, cfg=cfg)
            row.result = res.to_jsonable() | ({"llm_output": _label(trace)} if trace else {})
            row.latency_ms = int((time.perf_counter() - t0) * 1000)
            if run.explain and setup.engine == "llm":
                try:
                    ex: dict[str, Any] = dict(explain(setup, text_views.full))
                    ex["same_tier"] = ex["tier"] == res.zero_shot_tier.value
                    row.explanation = ex
                except Exception as exc:  # noqa: BLE001 — the tier stands without an explanation
                    row.explanation = {"error": f"{type(exc).__name__}: {exc}"[:500]}
            row.status = "done"
        except Exception as exc:  # noqa: BLE001 — one failed setup must not stop the others
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            if trace:  # an unusable answer: keep what the model said, so the failure can be read
                row.result = {"llm_output": _label(trace)}
            row.latency_ms = int((time.perf_counter() - t0) * 1000)
        row.finished_at = datetime.now(UTC)
        db.session.commit()


def _label(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """classify_views classifies the full text first, then (D2) the visible text."""
    return [{"view": v} | t for v, t in zip(("full", "visible"), trace, strict=False)]


# ---------- payloads ----------


def run_payload(run: PlaygroundRun, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(run.id), "title": run.title, "created_at": run.created_at.isoformat(),
        "status": run.status, "input_kind": run.input_kind, "input_ref": run.input_ref,
        "attack": run.attack, "attack_source": run.attack_source, "explain": run.explain,
        "preset": run.preset, "rows": len(run.rows),
        "done": sum(r.status in ("done", "failed") for r in run.rows),
    }  # fmt: skip
    if detail:
        out["documents"] = {d.kind: {"filename": d.filename, "content_type": d.content_type,
                                     "size_bytes": d.size_bytes} for d in run.documents}  # fmt: skip
        out["rows"] = [{
            "id": str(r.id), "position": r.position, "setup": r.setup, "status": r.status,
            "result": r.result, "explanation": r.explanation, "error": r.error,
            "latency_ms": r.latency_ms,
        } for r in run.rows]  # fmt: skip
    return out
