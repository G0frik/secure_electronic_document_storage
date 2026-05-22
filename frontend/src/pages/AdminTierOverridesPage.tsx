import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  approveOverride,
  denyOverride,
  listAdminOverrides,
  OverrideStatus,
  TierOverrideRequest,
} from "@/api/tierOverrides";
import { useAuth } from "@/state/auth";
import AdminShell from "@/components/AdminShell";

const FILTERS: { value: OverrideStatus | "all"; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "denied", label: "Denied" },
  { value: "all", label: "All" },
];

export default function AdminTierOverridesPage() {
  const { user } = useAuth();
  const [filter, setFilter] = useState<OverrideStatus | "all">("pending");
  const [items, setItems] = useState<TierOverrideRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listAdminOverrides(filter);
      setItems(rows);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load requests.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onApprove(req: TierOverrideRequest) {
    const reason = window.prompt(
      `Approve ${req.current_tier} → ${req.requested_tier} for "${req.filename}"?\nOptional decision reason:`,
      "",
    );
    if (reason === null) return;
    try {
      await approveOverride(req.id, reason || undefined);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Approve failed — see console.");
    }
  }

  async function onDeny(req: TierOverrideRequest) {
    const reason = window.prompt(
      `Deny request for "${req.filename}"?\nReason (shown to the requester):`,
      "",
    );
    if (reason === null) return;
    try {
      await denyOverride(req.id, reason || undefined);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Deny failed — see console.");
    }
  }

  return (
    <AdminShell>
      <h1>Tier override requests</h1>
      <p style={{ color: "#6e7781" }}>
        Signed in as <strong>{user?.email}</strong> (admin).
      </p>

      <p style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        Filter:
        {FILTERS.map((f) => (
          <button key={f.value} onClick={() => setFilter(f.value)} disabled={filter === f.value}>
            {f.label}
          </button>
        ))}
      </p>

      {loading && <p className="status-pending">Loading…</p>}
      {error && <p className="status-fail">{error}</p>}

      {!loading && !error && items.length === 0 && (
        <p className="status-pending">No requests in this view.</p>
      )}

      {!loading && !error && items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
              <th style={{ padding: "0.5rem" }}>File</th>
              <th style={{ padding: "0.5rem" }}>Requested by</th>
              <th style={{ padding: "0.5rem" }}>Change</th>
              <th style={{ padding: "0.5rem" }}>Justification</th>
              <th style={{ padding: "0.5rem" }}>Status</th>
              <th style={{ padding: "0.5rem" }}>Filed</th>
              <th style={{ padding: "0.5rem" }}></th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id} style={{ borderBottom: "1px solid #eaeef2" }}>
                <td style={{ padding: "0.5rem" }}>{r.filename ?? "(removed)"}</td>
                <td style={{ padding: "0.5rem" }}>{r.requested_by_email ?? r.requested_by_id}</td>
                <td style={{ padding: "0.5rem" }}>
                  <code>{r.current_tier}</code> → <code>{r.requested_tier}</code>
                </td>
                <td
                  style={{
                    padding: "0.5rem",
                    maxWidth: "20rem",
                    fontStyle: "italic",
                    color: "#6e7781",
                  }}
                >
                  {r.justification}
                </td>
                <td style={{ padding: "0.5rem" }}>
                  <span
                    className={
                      r.status === "approved"
                        ? "status-ok"
                        : r.status === "denied"
                          ? "status-fail"
                          : "status-pending"
                    }
                  >
                    {r.status}
                  </span>
                  {r.decision_reason && (
                    <div style={{ fontSize: "0.85em", color: "#6e7781" }}>{r.decision_reason}</div>
                  )}
                </td>
                <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                  {new Date(r.created_at).toLocaleString()}
                </td>
                <td style={{ padding: "0.5rem" }}>
                  {r.status === "pending" && (
                    <>
                      <button onClick={() => onApprove(r)}>Approve</button>{" "}
                      <button onClick={() => onDeny(r)}>Deny</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminShell>
  );
}
