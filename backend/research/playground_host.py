"""Host side of the admin playground: llama-server in router mode + the GPU NLI server (stdlib only).

    python backend/research/playground_host.py start | stop | status

start: writes the router presets (one section per research model label, same server args as the
research runs: -c 8192, -ngl 999, -np 1, plus the per-model extras), starts llama-server on :18080
(--models-max 1: one LLM in VRAM at a time; models load on first request) and nli_server.py on :18081
in the host .venv, then waits until both answer. stop: kills both. The playground worker frees the GPU
between NLI and LLM rows through their unload endpoints.
"""

# Local operator tool: starts local processes (llama-server, the NLI server).
# ruff: noqa: S603, S607, S310

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LLAMA = Path.home() / "llm/llama.cpp/b12317/llama-server.exe"
MODELS = Path.home() / "llm/models"
VENV_PY = REPO / ".venv/Scripts/python.exe"
STATE = HERE / "results" / "playground_host"
LLM_PORT, NLI_PORT = 18080, 18081

# research label -> (GGUF file, extra llama-server args as preset keys)
PRESETS: dict[str, tuple[str, dict[str, str]]] = {
    "gemma4-12b": ("gemma-4-12b-it-qat-q4_0.gguf", {}),
    "gemma4-e4b": ("gemma-4-E4B_q4_0-it.gguf", {}),
    "gemma4-e2b": ("gemma-4-E2B_q4_0-it.gguf", {}),
    "qwen35-9b": ("Qwen3.5-9B-Q4_K_M.gguf", {}),
    "qwen35-9b-think1k": ("Qwen3.5-9B-Q4_K_M.gguf", {"reasoning-budget": "1024"}),
    "qwen35-4b": ("Qwen3.5-4B-Q4_K_M.gguf", {}),
    "qwen35-2b": ("Qwen3.5-2B-Q4_K_M.gguf", {}),
    "gemma3-12b": ("gemma-3-12b-it-Q4_K_M.gguf", {}),
    "mamaylm-12b": ("MamayLM-Gemma-3-12B-IT-v2.0-Q4_K_M.gguf", {}),
    "lapa-12b": ("lapa-v0.1.2-instruct-Q4_K_M.gguf", {}),
    "ministral3-14b": ("Ministral-3-14B-Instruct-2512-Q4_K_M.gguf", {}),
    "ministral3-3b": ("Ministral-3-3B-Instruct-2512-Q4_K_M.gguf", {}),
    "gpt-oss-20b-low": ("gpt-oss-20b-MXFP4.gguf", {"n-cpu-moe": "8"}),
}


def presets_ini() -> str:
    out = []
    for label, (gguf, extra) in PRESETS.items():
        if not (MODELS / gguf).exists():
            continue
        keys = {"model": (MODELS / gguf).as_posix(), "ctx-size": "8192"} | extra
        out.append(f"[{label}]\n" + "".join(f"{k} = {v}\n" for k, v in keys.items()))
    return "\n".join(out)


def up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def spawn(cmd: list[str], log: Path) -> int:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    with log.open("ab") as f:
        return subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, creationflags=flags).pid


def start() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    pids: dict[str, int] = {}
    if not up(f"http://127.0.0.1:{LLM_PORT}/models"):
        ini = STATE / "presets.ini"
        ini.write_text(presets_ini(), encoding="utf-8")
        pids["llm"] = spawn([str(LLAMA), "--models-preset", str(ini), "--models-max", "1",
                             "-ngl", "999", "-np", "1", "--host", "127.0.0.1",
                             "--port", str(LLM_PORT)], STATE / "llama-server.log")  # fmt: skip
    if not up(f"http://127.0.0.1:{NLI_PORT}/"):
        pids["nli"] = spawn([str(VENV_PY), str(HERE / "nli_server.py"), "--port", str(NLI_PORT)],
                            STATE / "nli_server.log")  # fmt: skip
    if pids:
        (STATE / "pids.json").write_text(json.dumps(pids), encoding="utf-8")
    for _ in range(60):
        if up(f"http://127.0.0.1:{LLM_PORT}/models") and up(f"http://127.0.0.1:{NLI_PORT}/"):
            print(f"playground host ready: LLM router :{LLM_PORT}, NLI server :{NLI_PORT}")
            return
        time.sleep(2)
    sys.exit(f"servers did not come up; see {STATE}/*.log")


def stop() -> None:
    pids_file = STATE / "pids.json"
    if pids_file.exists():
        for pid in json.loads(pids_file.read_text(encoding="utf-8")).values():
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        pids_file.unlink()
    print("playground host stopped")


def status() -> None:
    for name, url in (("llm", f"http://127.0.0.1:{LLM_PORT}/models"),
                      ("nli", f"http://127.0.0.1:{NLI_PORT}/")):  # fmt: skip
        print(f"{name}: {'up' if up(url) else 'down'}")


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
