import { useEffect, useState } from "react";
import { listEvents, listGroups, listUsers } from "@/api/admin";
import AdminShell from "@/components/AdminShell";

export default function AdminHomePage() {
  const [users, setUsers] = useState<number | null>(null);
  const [groups, setGroups] = useState<number | null>(null);
  const [recent, setRecent] = useState<{ action: string; time: string }[]>([]);

  useEffect(() => {
    listUsers().then((u) => setUsers(u.length)).catch(() => setUsers(null));
    listGroups().then((g) => setGroups(g.length)).catch(() => setGroups(null));
    listEvents({ limit: 8 })
      .then((r) =>
        setRecent(
          r.items.map((e) => ({ action: e.event.action, time: e["@timestamp"] })),
        ),
      )
      .catch(() => setRecent([]));
  }, []);

  return (
    <AdminShell>
      <h1>Admin overview</h1>
      <p style={{ color: "#6e7781" }}>
        Consolidated administration for users, departments, groups, access
        policies, tier-override workflow, and the SIEM event stream.
      </p>

      <div style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
        <div
          style={{
            border: "1px solid #d0d7de",
            borderRadius: "6px",
            padding: "1rem",
            minWidth: "8rem",
          }}
        >
          <div style={{ fontSize: "0.85em", color: "#6e7781" }}>Users</div>
          <div style={{ fontSize: "1.6em" }}>{users ?? "—"}</div>
        </div>
        <div
          style={{
            border: "1px solid #d0d7de",
            borderRadius: "6px",
            padding: "1rem",
            minWidth: "8rem",
          }}
        >
          <div style={{ fontSize: "0.85em", color: "#6e7781" }}>Groups</div>
          <div style={{ fontSize: "1.6em" }}>{groups ?? "—"}</div>
        </div>
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>Recent events</h2>
      {recent.length === 0 ? (
        <p className="status-pending">No events yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #d0d7de" }}>
              <th style={{ padding: "0.4rem" }}>Action</th>
              <th style={{ padding: "0.4rem" }}>When</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((r, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #eaeef2" }}>
                <td style={{ padding: "0.4rem" }}><code>{r.action}</code></td>
                <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                  {new Date(r.time).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminShell>
  );
}
