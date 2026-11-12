"""Zero-shot NLI on the host GPU (ONNX Runtime + DirectML), served over HTTP like llama-server.

Runs on the Windows host, not in the container: DirectML is the only GPU path for the RX 6700 XT.
Needs a host venv with `optimum`, `onnxruntime-directml` and `transformers`; it does not import the app.

    python backend/research/nli_server.py [--port 8081] [--onnx-dir ~/.cache/doc_classifier_onnx]

POST /zero-shot {"model", "text", "labels", "template", "multi_label"} -> {"scores": {label: score}}
GET  /health -> onnxruntime version, providers, loaded models

The container side (research.engines.NliEngine with --nli-url) truncates the text and maps scores to a tier
exactly as the service does; this server only replaces the PyTorch-CPU forward pass.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

import onnxruntime as ort
from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer, pipeline

PROVIDER = "DmlExecutionProvider"
_pipes: dict[str, Any] = {}
_lock = Lock()  # one GPU, one request at a time
ONNX_DIR = Path.home() / ".cache" / "doc_classifier_onnx"


def get_pipe(model_id: str) -> Any:
    if model_id not in _pipes:
        d = ONNX_DIR / model_id.replace("/", "__")
        if not (d / "model.onnx").exists():
            raise FileNotFoundError(f"no ONNX export for {model_id} in {d}")
        model = ORTModelForSequenceClassification.from_pretrained(d, provider=PROVIDER)
        _pipes[model_id] = pipeline(
            "zero-shot-classification", model=model, tokenizer=AutoTokenizer.from_pretrained(d)
        )
    return _pipes[model_id]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._send(200, {"status": "ok", "onnxruntime": ort.__version__,
                         "providers": ort.get_available_providers(), "provider": PROVIDER,
                         "onnx_dir": str(ONNX_DIR), "loaded": sorted(_pipes)})  # fmt: skip

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with _lock:
                t0 = time.perf_counter()
                res = get_pipe(req["model"])(
                    req["text"], candidate_labels=req["labels"],
                    hypothesis_template=req["template"], multi_label=req["multi_label"],
                )  # fmt: skip
                ms = (time.perf_counter() - t0) * 1000
            scores = dict(zip(res["labels"], res["scores"], strict=False))
            self._send(200, {"scores": scores, "latency_ms": ms, "provider": PROVIDER})
        except Exception as exc:  # report to the client instead of dropping the connection
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, *args: Any) -> None:
        pass


def main() -> None:
    global ONNX_DIR
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--onnx-dir", type=Path, default=ONNX_DIR)
    args = p.parse_args()
    ONNX_DIR = args.onnx_dir.expanduser()
    if PROVIDER not in ort.get_available_providers():
        raise SystemExit(f"{PROVIDER} not available: install onnxruntime-directml")
    print(
        f"NLI server on http://127.0.0.1:{args.port} ({PROVIDER}, models from {ONNX_DIR})",
        flush=True,
    )
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
