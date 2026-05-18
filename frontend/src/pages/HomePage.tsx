import { useEffect, useState } from "react";
import { fetchHealth } from "@/api/health";

type FetchState =
  | { kind: "loading" }
  | { kind: "ok"; status: string }
  | { kind: "error"; message: string };

export default function HomePage() {
  const [state, setState] = useState<FetchState>({ kind: "loading" });

  useEffect(() => {
    fetchHealth()
      .then((data) => setState({ kind: "ok", status: data.status }))
      .catch((err: Error) => setState({ kind: "error", message: err.message }));
  }, []);

  return (
    <main>
      <h1>Secure Document Storage</h1>
      <p>Phase 0 — infrastructure foundation.</p>

      <h2>Backend health</h2>
      {state.kind === "loading" && (
        <p className="status-pending">
          Checking <code>/healthz</code>…
        </p>
      )}
      {state.kind === "ok" && (
        <p>
          <code>/healthz</code> → <span className="status-ok">{state.status}</span>
        </p>
      )}
      {state.kind === "error" && (
        <p>
          <code>/healthz</code> → <span className="status-fail">unreachable</span>
          <br />
          <small>{state.message}</small>
        </p>
      )}
    </main>
  );
}
