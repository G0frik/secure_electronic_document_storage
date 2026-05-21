import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  AdminEventEnvelope,
  listEvents,
} from "@/api/admin";
import AdminShell from "@/components/AdminShell";

type Severity = "info" | "warning" | "critical" | "";

export default function AdminEventsPage() {
  const [items, setItems] = useState<AdminEventEnvelope[]>([]);
  const [count, setCount] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const [action, setAction] = useState<string>("");
  const [severity, setSeverity] = useState<Severity>("");
  const [limit, setLimit] = useState<number>(100);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listEvents({
        action: action.trim() || undefined,
        severity: severity || undefined,
        limit,
      });
      setItems(data.items);
      setCount(data.count);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load events.");
    } finally {
      setLoading(false);
    }
  }, [action, severity, limit]);

  useEffect(() => {
    refresh();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AdminShell>
      <h1>Events / SIEM stream</h1>
      <p style={{ color: "#6e7781" }}>
        ECS-shaped audit stream. Same payload Filebeat / Wazuh agent reads
        from <code>./logs/events.jsonl</code>.
      </p>

      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          margin: "1rem 0",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <input
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="action (e.g. share_link.downloaded)"
          style={{ padding: "0.4rem", minWidth: "20rem" }}
        />
        <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          <option value="">any severity</option>
          <option value="info">info</option>
          <option value="warning">warning</option>
          <option value="critical">critical</option>
        </select>
        <label>
          Limit:{" "}
          <input
            type="number"
            value={limit}
            min={1}
            max={1000}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ width: "5rem" }}
          />
        </label>
        <button onClick={refresh} disabled={loading}>
          {loading ? "Loading…" : "Search"}
        </button>
      </div>

      {error && <p className="status-fail">{error}</p>}
      <p style={{ color: "#6e7781" }}>{count} event(s).</p>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9em" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.4rem" }}>Timestamp</th>
            <th style={{ padding: "0.4rem" }}>Action</th>
            <th style={{ padding: "0.4rem" }}>Outcome</th>
            <th style={{ padding: "0.4rem" }}>User</th>
            <th style={{ padding: "0.4rem" }}>IP</th>
            <th style={{ padding: "0.4rem" }}>Message</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.event.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {new Date(e["@timestamp"]).toLocaleString()}
              </td>
              <td style={{ padding: "0.4rem" }}>
                <code>{e.event.action}</code>
              </td>
              <td
                style={{
                  padding: "0.4rem",
                  color: e.event.outcome === "failure" ? "#d1242f" : "#1f883d",
                }}
              >
                {e.event.outcome}
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {e.user?.email ?? e.user?.id ?? "—"}
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {e.source?.ip ?? "—"}
              </td>
              <td style={{ padding: "0.4rem" }}>{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </AdminShell>
  );
}
