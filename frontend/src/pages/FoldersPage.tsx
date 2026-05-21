import { FormEvent, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { createFolder, deleteFolder, Folder, listFolders } from "@/api/folders";
import { listGranted, revokeShare, Share } from "@/api/shares";
import { listGrantedLinks, revokeShareLink, ShareLink } from "@/api/shareLinks";
import Breadcrumb from "@/components/Breadcrumb";
import ShareDialog from "@/components/ShareDialog";
import { Folder as FolderIcon, Plus, Share2, Trash2 } from "@/components/icons";

/**
 * Folders + sharing overview.
 *
 * Three cards inside one page: folder CRUD, internal shares granted,
 * external share links. Each card uses the shared `.table` styling.
 */
export default function FoldersPage() {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [grantedShares, setGrantedShares] = useState<Share[]>([]);
  const [grantedLinks, setGrantedLinks] = useState<ShareLink[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState("");
  const [newParent, setNewParent] = useState<string | null>(null);

  const [shareTarget, setShareTarget] = useState<Folder | null>(null);

  async function refresh() {
    try {
      const [fs, gs, gl] = await Promise.all([
        listFolders(),
        listGranted(),
        listGrantedLinks(),
      ]);
      setFolders(fs);
      setGrantedShares(gs);
      setGrantedLinks(gl);
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

  async function onRevokeLink(link: ShareLink) {
    if (!window.confirm(`Revoke external link for "${link.filename}"?`)) return;
    try {
      await revokeShareLink(link.id);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Revoke failed — see console.");
    }
  }

  function linkStatus(link: ShareLink): { label: string; tone: "ok" | "warn" | "fail" } {
    if (link.revoked_at) return { label: "Revoked", tone: "fail" };
    if (link.expires_at && new Date(link.expires_at) <= new Date()) {
      return { label: "Expired", tone: "fail" };
    }
    if (link.max_uses !== null && link.use_count >= link.max_uses) {
      return { label: "Exhausted", tone: "warn" };
    }
    return { label: "Active", tone: "ok" };
  }

  return (
    <div className="page">
      <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Folders & shares" }]} />

      <div className="page-header">
        <div className="page-title">
          <h1>Folders &amp; shares</h1>
          <span className="page-subtitle">
            Create folders, manage internal shares, and revoke external links.
          </span>
        </div>
      </div>

      {/* --- New folder --- */}
      <div className="card" style={{ marginBottom: "var(--space-5)" }}>
        <div className="card-header row row-2">
          <Plus size={14} />
          New folder
        </div>
        <div className="card-body">
          <form onSubmit={onCreate} className="row row-3" style={{ flexWrap: "wrap" }}>
            <input
              type="text"
              className="input"
              style={{ width: "auto", flex: "1 1 240px" }}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Folder name"
              required
            />
            <select
              className="select"
              style={{ width: "auto", flex: "0 0 200px" }}
              value={newParent ?? ""}
              onChange={(e) => setNewParent(e.target.value || null)}
            >
              <option value="">— root —</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !newName.trim()}
            >
              Create
            </button>
          </form>
          {error && <p className="field-error" style={{ marginTop: "var(--space-3)" }}>{error}</p>}
        </div>
      </div>

      {/* --- Folders --- */}
      <div className="page-header">
        <div className="page-title">
          <h2>Your folders</h2>
        </div>
      </div>
      {folders.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No folders yet</div>
          <div className="text-small text-muted">Create one above to get started.</div>
        </div>
      ) : (
        <div className="card" style={{ marginBottom: "var(--space-5)" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Parent</th>
                <th>Created</th>
                <th className="cell-actions"></th>
              </tr>
            </thead>
            <tbody>
              {folders.map((f) => (
                <tr key={f.id}>
                  <td>
                    <span className="row row-3">
                      <FolderIcon size={16} className="text-muted" />
                      <span>{f.name}</span>
                    </span>
                  </td>
                  <td className="cell-muted">
                    {f.parent_id
                      ? folders.find((p) => p.id === f.parent_id)?.name ?? f.parent_id
                      : "—"}
                  </td>
                  <td className="cell-muted text-small">
                    {new Date(f.created_at).toLocaleString()}
                  </td>
                  <td className="cell-actions">
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => setShareTarget(f)}
                      title="Share folder"
                      aria-label="Share folder"
                    >
                      <Share2 size={14} />
                    </button>
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => onDelete(f)}
                      title="Delete folder (must be empty)"
                      aria-label="Delete folder"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* --- Shares granted --- */}
      <div className="page-header">
        <div className="page-title">
          <h2>Shares you granted</h2>
        </div>
      </div>
      {grantedShares.length === 0 ? (
        <div className="empty">
          <div className="empty-title">You haven't shared anything yet</div>
          <div className="text-small text-muted">
            Share a file from My files, or a folder from the table above.
          </div>
        </div>
      ) : (
        <div className="card" style={{ marginBottom: "var(--space-5)" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Target</th>
                <th>Kind</th>
                <th>Recipient</th>
                <th>Permission</th>
                <th>Granted</th>
                <th className="cell-actions"></th>
              </tr>
            </thead>
            <tbody>
              {grantedShares.map((s) => (
                <tr key={s.id}>
                  <td title={s.label}>
                    <span className="filename">{s.label}</span>
                  </td>
                  <td className="cell-muted text-small">{s.kind}</td>
                  <td>{s.recipient_email ?? s.recipient_id}</td>
                  <td className="cell-muted text-small">{s.permission}</td>
                  <td className="cell-muted text-small">
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                  <td className="cell-actions">
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => onRevokeShare(s)}
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* --- External links --- */}
      <div className="page-header">
        <div className="page-title">
          <h2>External share links</h2>
        </div>
      </div>
      {grantedLinks.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No external links yet</div>
          <div className="text-small text-muted">
            Mint one from the Share dialog on any file you own.
          </div>
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Uses</th>
                <th>Expires</th>
                <th>Created</th>
                <th className="cell-actions"></th>
              </tr>
            </thead>
            <tbody>
              {grantedLinks.map((l) => {
                const status = linkStatus(l);
                const toneClass =
                  status.tone === "ok"
                    ? "badge badge-public"
                    : status.tone === "warn"
                      ? "badge badge-confidential"
                      : "badge badge-restricted";
                return (
                  <tr key={l.id}>
                    <td title={l.filename ?? "(removed)"}>
                      <span className="filename">{l.filename ?? "(removed)"}</span>
                    </td>
                    <td>
                      <span className={toneClass}>{status.label}</span>
                    </td>
                    <td className="cell-muted text-mono text-small">
                      {l.use_count}
                      {l.max_uses !== null ? ` / ${l.max_uses}` : ""}
                    </td>
                    <td className="cell-muted text-small">
                      {l.expires_at ? new Date(l.expires_at).toLocaleString() : "—"}
                    </td>
                    <td className="cell-muted text-small">
                      {new Date(l.created_at).toLocaleString()}
                    </td>
                    <td className="cell-actions">
                      {!l.revoked_at && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => onRevokeLink(l)}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {shareTarget && (
        <ShareDialog
          targetType="folder"
          targetId={shareTarget.id}
          targetLabel={shareTarget.name}
          onClose={() => setShareTarget(null)}
          onShared={refresh}
        />
      )}
    </div>
  );
}
