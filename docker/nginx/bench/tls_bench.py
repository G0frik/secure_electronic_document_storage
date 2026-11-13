"""TLS 1.3 handshake cost per key-exchange group: X25519 vs X25519MLKEM768 vs MLKEM768.

    python docker/nginx/bench/tls_bench.py [--n 1000] [--out docker/nginx/bench/results]

Starts the stack's nginx image with bench-nginx.conf and a fresh RSA-2048 certificate on a private Docker
network, then a client container (OpenSSL >= 3.5 + curl) runs N fresh connections per group (one curl
process each, no session resumption) and records curl's time_connect / time_appconnect. Handshake
message sizes come from `openssl s_client -msg`. Writes raw.csv and summary.csv; stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SERVER_IMAGE = "nginx:1.28-alpine"
CLIENT_IMAGE = "alpine:3.22"  # OpenSSL 3.5, curl 8.14
GROUPS = ["X25519", "X25519MLKEM768", "MLKEM768"]
NET, SERVER, CERTS = "pqtls-bench", "pqtls-bench-server", "pqtls-bench-certs"


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, check=check, capture_output=True, text=True).stdout


def client(script: str) -> str:
    return sh("docker", "run", "--rm", "--network", NET, CLIENT_IMAGE, "sh", "-c",
              "apk add -q --no-cache openssl curl >/dev/null && " + script)  # fmt: skip


def hello_sizes(group: str) -> dict[str, int]:
    """Handshake message lengths (bytes, without the 4-byte handshake header) from s_client -msg."""
    out = client(f"echo | openssl s_client -connect {SERVER}:443 -tls1_3 -groups {group} -msg 2>&1")
    # OpenSSL names KEM groups in "Negotiated TLS1.3 group", classical ECDHE in "Peer Temp Key"
    assert f"Negotiated TLS1.3 group: {group}" in out or f"Peer Temp Key: {group}," in out, f"{group} not negotiated"
    sizes = {}
    for name in ("ClientHello", "ServerHello"):
        m = re.search(rf"TLS 1\.3, Handshake \[length ([0-9a-f]+)\], {name}", out)
        sizes[name] = int(m.group(1), 16) if m else -1
    return sizes


def pct(xs: list[float], q: float) -> float:
    return statistics.quantiles(xs, n=100, method="inclusive")[round(q * 100) - 1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--out", type=Path, default=HERE / "results")
    p.add_argument("--rounds", type=int, default=10, help="interleaved rounds; n is split evenly")
    p.add_argument("--warmup", type=int, default=20, help="discarded handshakes per group first")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sh("docker", "network", "create", NET, check=False)
    sh("docker", "rm", "-f", SERVER, check=False)
    # same certificate type as the stack (RSA-2048 from generate-certs.sh), in a throwaway volume
    sh("docker", "volume", "rm", CERTS, check=False)
    sh("docker", "run", "--rm", "-v", f"{CERTS}:/certs",
       "-v", f"{REPO / 'docker/nginx/generate-certs.sh'}:/generate-certs.sh:ro", CLIENT_IMAGE,
       "sh", "-c", "apk add -q --no-cache openssl >/dev/null && sh /generate-certs.sh")  # fmt: skip
    sh("docker", "run", "-d", "--name", SERVER, "--network", NET,
       "-v", f"{HERE / 'bench-nginx.conf'}:/etc/nginx/nginx.conf:ro",
       "-v", f"{CERTS}:/etc/nginx/certs:ro", SERVER_IMAGE)  # fmt: skip
    try:
        versions = client("openssl version; curl --version | head -1")
        server_v = sh("docker", "exec", SERVER, "sh", "-c", "nginx -V 2>&1", check=False)
        rows, summary = [], []
        sizes = {g: hello_sizes(g) for g in GROUPS}
        fmt = "%{time_connect} %{time_appconnect}\\n"

        def handshakes(g: str, n: int) -> list[tuple[float, float]]:
            out = client(
                f"for i in $(seq {n}); do curl -sk -o /dev/null --tlsv1.3 --tls-max 1.3 "
                f"--curves {g} -w '{fmt}' https://{SERVER}/; done"
            )
            return [(float(c) * 1000, float(a) * 1000) for c, a in (ln.split() for ln in out.strip().splitlines())]

        for g in GROUPS:  # warm-up, discarded: server caches, CPU frequency
            handshakes(g, args.warmup)
        # Interleaved rounds with a rotating group order, so drift over time hits every group alike.
        per_round = args.n // args.rounds
        measured: dict[str, list[tuple[float, float]]] = {g: [] for g in GROUPS}
        for r in range(args.rounds):
            for g in GROUPS[r % len(GROUPS):] + GROUPS[: r % len(GROUPS)]:
                measured[g] += handshakes(g, per_round)
        for g in GROUPS:
            conn, app = [], []
            for i, (c_ms, a_ms) in enumerate(measured[g]):
                conn.append(c_ms)
                app.append(a_ms)
                rows.append({"group": g, "i": i, "connect_ms": round(c_ms, 3), "appconnect_ms": round(a_ms, 3),
                             "tls_ms": round(a_ms - c_ms, 3)})  # fmt: skip
            sizes_g = sizes[g]
            tls = [a - c for a, c in zip(app, conn, strict=True)]
            assert len(tls) == per_round * args.rounds, (g, len(tls))
            summary.append({
                "group": g, "n": len(tls),
                "appconnect_median_ms": round(statistics.median(app), 3), "appconnect_p95_ms": round(pct(app, 0.95), 3),
                "tls_median_ms": round(statistics.median(tls), 3), "tls_p95_ms": round(pct(tls, 0.95), 3),
                "clienthello_bytes": sizes_g["ClientHello"], "serverhello_bytes": sizes_g["ServerHello"],
            })  # fmt: skip
            print(summary[-1], flush=True)
        for name, data in (("raw.csv", rows), ("summary.csv", summary)):
            with (args.out / name).open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        nginx_line = next((ln for ln in server_v.splitlines() if "OpenSSL" in ln), "")
        (args.out / "versions.txt").write_text(f"server: {SERVER_IMAGE} {nginx_line}\nclient: {CLIENT_IMAGE}\n{versions}",
                                               encoding="utf-8")  # fmt: skip
    finally:
        sh("docker", "rm", "-f", SERVER, check=False)
        sh("docker", "network", "rm", NET, check=False)
        sh("docker", "volume", "rm", CERTS, check=False)


if __name__ == "__main__":
    main()
