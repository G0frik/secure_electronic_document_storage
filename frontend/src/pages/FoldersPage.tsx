import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { createFolder, deleteFolder, Folder, listFolders } from "@/api/folders";
import { listGranted, revokeShare, Share } from "@/api/shares";
import { useAuth } from "@/state/auth";
import ShareDialog from "@/components/ShareDialog";

export default function FoldersPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [folders, setFolders] = useState<Folder[]>([]);
  const [grantedShares, setGrantedShares] = useState<Share[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState("");
  const [newParent, setNewParent] = useState<string | null>(null);

  const [shareTarget, setShareTarget] = useState<Folder | null>(null);

  async function refresh() {
    try {
      const [fs, gs] = await Promise.all([listFolders(), listGranted()]);
      setFolders(fs);
      setGrantedShares(gs);
    } catch (err) {
      console.warn(err);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await createFolder(newName, newParent);
      setNewName("");
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to create folder.");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(folder: Folder) {
    if (!window.confirm(`Delete folder "${folder.name}"? It must be empty.`)) return;
    try {
      await deleteFolder(folder.id);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Delete failed.");
    }
  }

  async function onRevokeShare(share: Share) {
    if (!window.confirm(`Revoke share of "${share.label}" with ${share.recipient_email}?`)) return;
    try {
      await revokeShare(share.id);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Revoke failed — see console.");
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
        <h1 style={{ margin: 0 }}>Folders</h1>
        <button onClick={() => navigate("/")}>← Back to files</button>
      </header>

      <p style={{ color: "#6e7781" }}>
        Signed in as <strong>{user?.email}</strong>
      </p>

      <section style={{ marginTop: "1rem" }}>
        <h2>New folder</h2>
        <form onSubmit={onCreate} style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Name"
            required
            style={{ padding: "0.5rem" }}
          />
          <select
            value={newParent ?? ""}
            onChange={(e) => setNewParent(e.target.value || null)}
            style={{ padding: "0.5rem" }}
          >
            <option value="">— root —</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          <button type="submit" disabled={busy || !newName.trim()}>
            Create
          </button>
        </form>
        {error && <p className="status-fail">{error}</p>}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Your folders</h2>
        {folders.length === 0 ? (
          <p className="status-pending">No folders yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
                <th style={{ padding: "0.5rem" }}>Name</th>
                <th style={{ padding: "0.5rem" }}>Parent</th>
                <th style={{ padding: "0.5rem" }}>Created</th>
                <th style={{ padding: "0.5rem" }}></th>
              </tr>
            </thead>
            <tbody>
              {folders.map((f) => (
                <tr key={f.id} style={{ borderBottom: "1px solid #eaeef2" }}>
                  <td style={{ padding: "0.5rem" }}>{f.name}</td>
                  <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                    {f.parent_id
                      ? folders.find((p) => p.id === f.parent_id)?.name ?? f.parent_id
                      : "—"}
                  </td>
                  <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                    {new Date(f.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: "0.5rem" }}>
                    <button onClick={() => setShareTarget(f)}>Share…</button>{" "}
                    <button onClick={() => onDelete(f)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Shares you granted</h2>
        {grantedShares.length === 0 ? (
          <p className="status-pending">You haven't shared anything yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
                <th style={{ padding: "0.5rem" }}>Target</th>
                <th style={{ padding: "0.5rem" }}>Kind</th>
                <th style={{ padding: "0.5rem" }}>Recipient</th>
                <th style={{ padding: "0.5rem" }}>Permission</th>
                <th style={{ padding: "0.5rem" }}>Granted</th>
                <th style={{ padding: "0.5rem" }}></th>
              </tr>
            </thead>
            <tbody>
              {grantedShares.map((s) => (
                <tr key={s.id} style={{ borderBottom: "1px solid #eaeef2" }}>
                  <td style={{ padding: "0.5rem" }}>{s.label}</td>
                  <td style={{ padding: "0.5rem", color: "#6e7781" }}>{s.kind}</td>
                  <td style={{ padding: "0.5rem" }}>{s.recipient_email ?? s.recipient_id}</td>
                  <td style={{ padding: "0.5rem" }}>{s.permission}</td>
                  <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: "0.5rem" }}>
                    <button onClick={() => onRevokeShare(s)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {shareTarget && (
        <ShareDialog
          targetType="folder"
          targetId={shareTarget.id}
          targetLabel={shareTarget.name}
          onClose={() => setShareTarget(null)}
          onShared={refresh}
        />
      )}
    </main>
  );
}
