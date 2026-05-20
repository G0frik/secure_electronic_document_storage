import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import {
  hardDeleteFile,
  listTrash,
  restoreFile,
  TrashedFile,
} from "@/api/files";
import { useAuth } from "@/state/auth";
import { formatBytes, formatDateTime } from "@/utils/format";

const RETENTION_DAYS = 30;

function daysLeft(deletedAt: string): number {
  const purgeAt = new Date(deletedAt).getTime() + RETENTION_DAYS * 24 * 60 * 60 * 1000;
  return Math.max(0, Math.ceil((purgeAt - Date.now()) / (24 * 60 * 60 * 1000)));
}

export default function TrashPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<TrashedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listTrash();
      setItems(rows);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load trash.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onRestore(file: TrashedFile) {
    try {
      await restoreFile(file.id);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Restore failed — see console.");
    }
  }

  async function onHardDelete(file: TrashedFile) {
    if (
      !window.confirm(
        `Permanently delete "${file.original_filename}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await hardDeleteFile(file.id);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Delete failed — see console.");
    }
  }

  return (
    <main>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          borderBottom: "1px solid #eaeef2",
          paddingBottom: "0.75rem",
          marginBottom: "1.25rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Trash</h1>
        <button onClick={() => navigate("/")}>← Back to files</button>
      </header>

      <p style={{ color: "#6e7781" }}>
        Signed in as <strong>{user?.email}</strong>. Files older than{" "}
        {RETENTION_DAYS} days are deleted permanently.
      </p>

      {loading && <p className="status-pending">Loading trash…</p>}
      {error && <p className="status-fail">{error}</p>}

      {!loading && !error && items.length === 0 && (
        <p className="status-pending">Trash is empty.</p>
      )}

      {!loading && !error && items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
              <th style={{ padding: "0.5rem" }}>Name</th>
              <th style={{ padding: "0.5rem", textAlign: "right" }}>Size</th>
              <th style={{ padding: "0.5rem" }}>Deleted</th>
              <th style={{ padding: "0.5rem" }}>Days left</th>
              <th style={{ padding: "0.5rem" }}></th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr key={f.id} style={{ borderBottom: "1px solid #eaeef2" }}>
                <td style={{ padding: "0.5rem" }}>{f.original_filename}</td>
                <td style={{ padding: "0.5rem", textAlign: "right" }}>
                  {formatBytes(f.size_bytes)}
                </td>
                <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                  {formatDateTime(f.deleted_at)}
                </td>
                <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                  {daysLeft(f.deleted_at)}
                </td>
                <td style={{ padding: "0.5rem" }}>
                  <button onClick={() => onRestore(f)}>Restore</button>{" "}
                  <button onClick={() => onHardDelete(f)}>Delete now</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
