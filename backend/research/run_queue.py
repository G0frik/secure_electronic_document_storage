"""Run a queue of harness runs unattended, one engine on the GPU at a time (host side, stdlib only).

    python backend/research/run_queue.py queue.json [--dry-run]

Per entry: stop old servers, start the entry's server (llama-server or the NLI server), wait until it is
healthy, run `classify_dir` in the worker container. A non-zero exit (crash, server died, five engine
failures in a row) restarts the server and reruns the same run id, which resumes where it stopped, up to
`--attempts` times. Everything is logged with timestamps to <log_dir>/queue.log; <log_dir>/STATUS.json
shows the current entry and how many rows are on disk.

queue.json: {"log_dir": "...", "common": "<harness args for every run>", "runs": [
  {"label": "nli", "server": "nli", "harness": "--configs nli_en,nli_ml --nli-url ...", "run_id": "..."},
  {"label": "gemma4-e4b", "server": "llm", "gguf": "file.gguf", "server_args": "-c 8192",
   "harness": "--configs llm --llm-url ... --llm-label gemma4-e4b --gguf file.gguf", "run_id": "..."}]}
`--out` must be in `common`; the predictions of a run are <out>/<run_id>/predictions.csv (container path,
`/app/...` maps to backend/ on the host).
"""

# Local operator tool: starts local processes (llama-server, docker, git) from a local queue file.
# ruff: noqa: S603, S607, S310

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LLAMA = Path.home() / "llm/llama.cpp/b12317/llama-server.exe"
MODELS = Path.home() / "llm/models"
VENV_PY = REPO / ".venv/Scripts/python.exe"
HEALTH = {"llm": "http://127.0.0.1:18080/health", "nli": "http://127.0.0.1:18081/"}


def log(log_dir: Path, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with (log_dir / "queue.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def host_path(container_path: str) -> Path:
    return REPO / "backend" / container_path.removeprefix("/app/")


def rows_on_disk(common: str, run_id: str) -> int:
    args = shlex.split(common)
    out = args[args.index("--out") + 1]
    pred = host_path(out) / run_id / "predictions.csv"
    if not pred.exists():
        return 0
    with pred.open(encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def stop_servers(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        p.terminate()
    procs.clear()
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    time.sleep(3)


def start_server(entry: dict, log_dir: Path, procs: list[subprocess.Popen]) -> bool:
    out = (log_dir / f"server_{entry['label']}.log").open("a", encoding="utf-8")
    if entry["server"] == "nli":
        cmd = [str(VENV_PY), str(REPO / "backend/research/nli_server.py"), "--port", "18081"]
    else:
        cmd = [str(LLAMA), "-m", str(MODELS / entry["gguf"]), "-ngl", "999", "-np", "1",
               "--host", "127.0.0.1", "--port", "18080", *shlex.split(entry.get("server_args", ""))]  # fmt: skip
    procs.append(subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT))
    for _ in range(180):  # big GGUFs need a while to load
        try:
            if b"ok" in urllib.request.urlopen(HEALTH[entry["server"]], timeout=2).read():
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


def harness_cmd(common: str, entry: dict, git_commit: str) -> list[str]:
    args = shlex.split(common) + shlex.split(entry["harness"]) + ["--run-id", entry["run_id"]]
    if entry.get("files"):
        args += ["--files", entry["files"]]
    return ["docker", "compose", "run", "--rm", "--no-deps", "-T", "-e", f"GIT_COMMIT={git_commit}",
            "-v", f"{MODELS}:/models:ro", "worker", "python", "-m", "research.classify_dir", *args]  # fmt: skip


def run_entry(entry: dict, common: str, log_dir: Path, attempts: int, git_commit: str,
              start: Callable[[dict], bool], stop: Callable[[], None],
              run: Callable[[list[str], Path], int]) -> bool:  # fmt: skip
    """Run one queue entry with restarts; True when the harness finished (exit 0)."""
    for attempt in range(1, attempts + 1):
        stop()
        log(log_dir, f"{entry['label']}: attempt {attempt}, starting {entry['server']} server")
        if not start(entry):
            log(log_dir, f"{entry['label']}: server not healthy")
            continue
        status = {"label": entry["label"], "run_id": entry["run_id"], "attempt": attempt, "state": "running",
                  "rows_before": rows_on_disk(common, entry["run_id"]), "since": time.strftime("%H:%M:%S")}  # fmt: skip
        (log_dir / "STATUS.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
        rc = run(harness_cmd(common, entry, git_commit), log_dir / f"{entry['run_id']}.log")
        log(
            log_dir,
            f"{entry['label']}: harness exit {rc}, rows on disk {rows_on_disk(common, entry['run_id'])}",
        )
        if rc == 0:
            return True
    log(log_dir, f"{entry['label']}: GIVING UP after {attempts} attempts")
    return False


def _run(cmd: list[str], logfile: Path) -> int:
    with logfile.open("a", encoding="utf-8") as f:
        return subprocess.run(
            cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        ).returncode


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("queue", type=Path)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--dry-run", action="store_true", help="print the harness commands only")
    args = p.parse_args()
    q = json.loads(args.queue.read_text(encoding="utf-8"))
    log_dir = Path(q["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    git_commit = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=REPO, capture_output=True,
                                text=True).stdout.strip()  # fmt: skip
    if args.dry_run:
        for e in q["runs"]:
            print(" ".join(harness_cmd(q["common"], e, git_commit)))
        return
    procs: list[subprocess.Popen] = []
    results = {}
    try:
        for e in q["runs"]:
            results[e["label"]] = run_entry(e, q["common"], log_dir, args.attempts, git_commit,
                                            lambda x: start_server(x, log_dir, procs),
                                            lambda: stop_servers(procs), _run)  # fmt: skip
    finally:
        stop_servers(procs)
    log(log_dir, f"queue done: {results}")
    (log_dir / "STATUS.json").write_text(
        json.dumps({"state": "done", "results": results}), encoding="utf-8"
    )
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
