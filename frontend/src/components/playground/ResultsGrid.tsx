import { Fragment, useEffect, useState } from "react";
import type { Tier } from "@/api/files";
import { apiMessage, fetchLlmOutput, type LlmOutput, type Row } from "@/api/playground";
import { setupName } from "@/components/playground/setups";

const LABEL: Record<Tier, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
};

export function TierPill({ tier }: { tier?: Tier | null }) {
  if (!tier) return <span className="text-muted">—</span>;
  return <span className={`badge badge-${tier}`}>{LABEL[tier]}</span>;
}

function seconds(ms: number | null): string {
  return ms == null ? "" : `${(ms / 1000).toFixed(1)} s`;
}

/** One row per setup: the tiers, what each defense did, time; click a row for the details. */
export default function ResultsGrid({ runId, rows }: { runId: string; rows: Row[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const expected = rows.some((r) => r.setup.expected_tier);

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="table pg-results">
        <thead>
          <tr>
            <th>#</th>
            <th>Setup</th>
            <th>Final tier</th>
            {expected && <th>Recorded result</th>}
            <th>Semantic</th>
            <th>Presidio</th>
            <th>D2 views</th>
            <th>D4</th>
            <th className="cell-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const res = r.result;
            const views = res?.config.view_tiers;
            const score = res?.config.detector_score;
            const isOpen = open === r.id;
            return (
              <Fragment key={r.id}>
                <tr
                  className="pg-result-row"
                  aria-expanded={isOpen}
                  tabIndex={0}
                  onClick={() => setOpen(isOpen ? null : r.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setOpen(isOpen ? null : r.id);
                    }
                  }}
                >
                  <td className="cell-muted">{r.position + 1}</td>
                  <td>
                    <span className="text-mono text-small">{setupName(r.setup)}</span>
                  </td>
                  <td>
                    {r.status === "done" && <TierPill tier={res?.final_tier} />}
                    {(r.status === "pending" || r.status === "running") && (
                      <span className="badge badge-pending">
                        {r.status === "running" ? "running…" : "queued"}
                      </span>
                    )}
                    {r.status === "failed" && (
                      <span className="badge badge-failed" title={r.error ?? ""}>
                        Failed
                      </span>
                    )}
                    {res?.needs_review && (
                      <span className="text-small" style={{ color: "var(--color-danger)" }}>
                        {" "}
                        review
                      </span>
                    )}
                  </td>
                  {expected && (
                    <td>
                      <TierPill tier={r.setup.expected_tier} />
                      {r.setup.expected_tier && res && (
                        <span className="text-small text-muted">
                          {res.final_tier === r.setup.expected_tier ? " ✓ same" : " ≠ differs"}
                        </span>
                      )}
                    </td>
                  )}
                  <td>{res && <TierPill tier={res.zero_shot_tier} />}</td>
                  <td>
                    {res && r.setup.presidio === false ? (
                      <span className="text-small text-muted">off</span>
                    ) : (
                      res && <TierPill tier={res.presidio_tier} />
                    )}
                  </td>
                  <td className="text-small">
                    {views ? (
                      <>
                        full <TierPill tier={views.full} /> visible{" "}
                        <TierPill tier={views.visible} />
                      </>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="text-small">
                    {score != null ? (
                      <span style={{ color: score >= 0.5 ? "var(--color-danger)" : undefined }}>
                        {score.toFixed(3)}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="cell-right text-small text-mono">{seconds(r.latency_ms)}</td>
                </tr>
                {isOpen && (
                  <tr className="pg-detail">
                    <td />
                    <td colSpan={expected ? 8 : 7}>
                      <RowDetail runId={runId} row={r} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The model's raw answer and reasoning, fetched when the row is opened (they can be long). */
function LlmOutputs({ runId, rowId }: { runId: string; rowId: string }) {
  const [items, setItems] = useState<LlmOutput[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchLlmOutput(runId, rowId).then(
      (v) => !cancelled && setItems(v),
      (e: unknown) => !cancelled && setError(apiMessage(e, "request failed")),
    );
    return () => {
      cancelled = true;
    };
  }, [runId, rowId]);
  if (error) return <p className="text-muted">Model's answer could not be loaded: {error}</p>;
  if (!items) return <p className="text-muted">Loading the model's answer…</p>;
  return (
    <>
      {items.map((o) => (
        <details key={o.view}>
          <summary>
            <strong>Model's answer</strong>
            {items.length > 1 && ` (${o.view === "full" ? "full text" : "visible text"})`}
            {o.reasoning ? " and reasoning" : ""}
            {o.truncated && <span className="text-muted"> · document cut to the word limit</span>}
          </summary>
          {o.reasoning && (
            <>
              <p className="text-muted" style={{ margin: "var(--space-2) 0 0" }}>
                Reasoning
              </p>
              <pre className="pg-raw">{o.reasoning}</pre>
            </>
          )}
          <p className="text-muted" style={{ margin: "var(--space-2) 0 0" }}>
            Raw answer
          </p>
          <pre className="pg-raw">{o.raw || "(empty)"}</pre>
        </details>
      ))}
    </>
  );
}

function RowDetail({ runId, row }: { runId: string; row: Row }) {
  const res = row.result;
  const ex = row.explanation;
  const scores = Object.entries(res?.raw_scores ?? {}).sort((a, b) => b[1] - a[1]);
  const entities = Object.entries(res?.presidio_entities ?? {});
  return (
    <div className="stack stack-2 text-small">
      {row.error && (
        <p className="field-error" style={{ margin: 0 }}>
          {row.error}
        </p>
      )}
      {ex?.reason && (
        <p style={{ margin: 0 }}>
          <strong>Model's explanation:</strong> “{ex.reason}”{" "}
          {ex.same_tier === false && (
            <span style={{ color: "var(--color-warning)" }}>
              (the explaining call chose <TierPill tier={ex.tier} />, not the tier shown)
            </span>
          )}
        </p>
      )}
      {ex?.error && (
        <p className="text-muted" style={{ margin: 0 }}>
          Explanation failed: {ex.error}
        </p>
      )}
      {row.has_llm_output && <LlmOutputs runId={runId} rowId={row.id} />}
      {res && (
        <p style={{ margin: 0 }}>
          <strong>Categories:</strong>{" "}
          {res.categories_triggered.length ? res.categories_triggered.join(", ") : "none"}
        </p>
      )}
      {scores.length > 0 && (
        <p style={{ margin: 0 }}>
          <strong>NLI scores:</strong>{" "}
          <span className="text-mono">
            {scores.map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ")}
          </span>
        </p>
      )}
      {entities.length > 0 && (
        <p style={{ margin: 0 }}>
          <strong>Presidio found:</strong>{" "}
          {entities.map(([k, v]) => `${k} ×${v.count ?? 1}`).join(", ")}
        </p>
      )}
    </div>
  );
}
