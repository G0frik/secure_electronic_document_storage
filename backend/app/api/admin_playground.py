"""Admin playground API. Registered only when PLAYGROUND=1 (see app.api.register_blueprints)."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from flask import Blueprint, Response, abort, jsonify, request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.playground import PlaygroundRun, PlaygroundSetup
from app.schemas.playground import DocumentRequest, RunCreateRequest, SetupSaveRequest
from app.services import audit, csrf, playground
from app.services import playground_attacks as attacks
from app.utils.auth_decorators import admin_required, current_user_or_none

bp = Blueprint("admin_playground", __name__, url_prefix="/api/admin/playground")


def _actor() -> Any:
    actor = current_user_or_none()
    if actor is None:  # admin_required already guarantees a user
        abort(401)
    return actor


def _parse(model: type, body: Any) -> Any:
    try:
        return model.model_validate(body or {})
    except ValidationError as exc:
        abort(400, description="; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ))  # fmt: skip


def _run_or_404(run_id: uuid.UUID) -> PlaygroundRun:
    run = playground.get_run(run_id)
    if run is None:
        abort(404, description="Run not found.")
    return run


def _doc_payload(doc: attacks.Doc) -> dict[str, Any]:
    return {"filename": doc.filename, "content_type": doc.content_type,
            "data_b64": base64.b64encode(doc.data).decode(), "views": playground.views(doc)}  # fmt: skip


@bp.get("/catalog")
@admin_required
def catalog():  # type: ignore[no-untyped-def]
    return jsonify(playground.catalog()), 200


@bp.get("/corpus")
@admin_required
def corpus():  # type: ignore[no-untyped-def]
    return jsonify({"items": attacks.corpus_index()}), 200


@bp.get("/files")
@admin_required
def files_list():  # type: ignore[no-untyped-def]
    q = (request.args.get("q") or "")[:100]
    items = [{"id": str(f.id), "filename": f.original_filename, "owner": email,
              "size_bytes": f.size_bytes, "uploaded_at": f.uploaded_at.isoformat()}
             for f, email in playground.list_files(q)]  # fmt: skip
    return jsonify({"items": items}), 200


@bp.post("/document")
@admin_required
@csrf.csrf_protect
def document():  # type: ignore[no-untyped-def]
    """The input and the attacked document (bytes + extracted views) before running anything."""
    req = _parse(DocumentRequest, request.get_json(silent=True))
    try:
        doc, attacked, source, info = playground.build(req, _actor())
    except playground.PlaygroundError as exc:
        abort(400, description=str(exc))
    return jsonify({"input": _doc_payload(doc), "attacked": _doc_payload(attacked),
                    "attack_source": source,
                    "info": {k: v for k, v in info.items() if k != "ref"}}), 200  # fmt: skip


@bp.post("/runs")
@admin_required
@csrf.csrf_protect
def create_run():  # type: ignore[no-untyped-def]
    req = _parse(RunCreateRequest, request.get_json(silent=True))
    try:
        run = playground.create_run(req, _actor())
    except playground.PlaygroundError as exc:
        abort(400, description=str(exc))
    from app.tasks.playground import run_playground

    run_playground.delay(str(run.id))
    return jsonify(playground.run_payload(run, detail=True)), 202


@bp.get("/runs")
@admin_required
def list_runs():  # type: ignore[no-untyped-def]
    offset = max(0, request.args.get("offset", 0, type=int))
    runs = playground.list_runs(limit=50, offset=offset)
    return jsonify({"items": [playground.run_payload(r) for r in runs]}), 200


@bp.get("/runs/<uuid:run_id>")
@admin_required
def get_run(run_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return jsonify(playground.run_payload(_run_or_404(run_id), detail=True)), 200


@bp.get("/runs/<uuid:run_id>/document")
@admin_required
def run_document(run_id: uuid.UUID):  # type: ignore[no-untyped-def]
    which = request.args.get("which", "attacked")
    run = _run_or_404(run_id)
    stored = next((d for d in run.documents if d.kind == which), None)
    if stored is None:
        abort(404, description="No such document.")
    doc = playground.load(stored)
    if request.args.get("format") == "raw":
        return Response(doc.data, mimetype=doc.content_type,
                        headers={"Cache-Control": "no-store"})  # fmt: skip
    return jsonify(_doc_payload(doc)), 200


@bp.post("/runs/<uuid:run_id>/rerun")
@admin_required
@csrf.csrf_protect
def rerun(run_id: uuid.UUID):  # type: ignore[no-untyped-def]
    new = playground.rerun(_run_or_404(run_id), _actor())
    from app.tasks.playground import run_playground

    run_playground.delay(str(new.id))
    return jsonify(playground.run_payload(new, detail=True)), 202


@bp.delete("/runs/<uuid:run_id>")
@admin_required
@csrf.csrf_protect
def delete_run(run_id: uuid.UUID):  # type: ignore[no-untyped-def]
    playground.delete_run(_run_or_404(run_id), _actor())
    return "", 204


@bp.get("/setups")
@admin_required
def list_setups():  # type: ignore[no-untyped-def]
    rows = db.session.scalars(select(PlaygroundSetup).order_by(PlaygroundSetup.name))
    return jsonify({"items": [{"id": str(s.id), "name": s.name, "rows": s.rows} for s in rows]}), 200


@bp.post("/setups")
@admin_required
@csrf.csrf_protect
def save_setup():  # type: ignore[no-untyped-def]
    req = _parse(SetupSaveRequest, request.get_json(silent=True))
    actor = _actor()
    for s in req.rows:
        try:
            playground.check_setup(s)
        except playground.PlaygroundError as exc:
            abort(400, description=str(exc))
    row = PlaygroundSetup(name=req.name, rows=[s.model_dump() for s in req.rows],
                          created_by_id=actor.id)  # fmt: skip
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, description="A saved setup with this name exists.")
    audit.record("playground.setup_saved", actor=actor, target_type="playground_setup",
                 target_id=row.id, metadata={"name": row.name})  # fmt: skip
    return jsonify({"id": str(row.id), "name": row.name, "rows": row.rows}), 201


@bp.delete("/setups/<uuid:setup_id>")
@admin_required
@csrf.csrf_protect
def delete_setup(setup_id: uuid.UUID):  # type: ignore[no-untyped-def]
    row = db.session.get(PlaygroundSetup, setup_id)
    if row is None:
        abort(404, description="Saved setup not found.")
    db.session.delete(row)
    db.session.commit()
    return "", 204
