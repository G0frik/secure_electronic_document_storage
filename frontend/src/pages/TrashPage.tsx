import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { hardDeleteFile, listTrash, restoreFile, TrashedFile } from "@/api/files";
import { formatBytes, formatDateTime } from "@/utils/format";
import Breadcrumb from "@/components/Breadcrumb";
import { FileGeneric, RotateCcw, Trash2 } from "@/components/icons";
import { useToast } from "@/state/toast";

const RETENTION_DAYS = 30;

function daysLeft(deletedAt: string): number {
  const purgeAt = new Date(deletedAt).getTime() + RETENTION_DAYS * 24 * 60 * 60 * 1000;
  return Math.max(0, Math.ceil((purgeAt - Date.now()) / (24 * 60 * 60 * 1000)));
}

/**
 * Trash — soft-deleted files awaiting purge or restore.
 *
 * Sits inside AppShell. Two icon-button actions per row (Restore +
 * Delete now). "Days left" is computed client-side from the 30-day
 * retention window the reaper enforces server-side.
 */
export default function TrashPage() {
  const toast = useToast();
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
      toast.success(`Restored "${file.original_filename}"`);
      await refresh();
    } catch (err) {
      console.error(err);
      toast.error("Restore failed", "See browser console for details.");
    }
  }

  async function onHardDelete(file: TrashedFile) {
    if (!window.confirm(`Permanently delete "${file.original_filename}"? This cannot be undone.`)) {
      return;
    }
    try {
      await hardDeleteFile(file.id);
      toast.success(`Deleted "${file.original_filename}" permanently`);
      await refresh();
    } catch (err) {
      console.error(err);
      toast.error("Delete failed", "See browser console for details.");
    }
  }

  return (
    <div className="page">
      <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Trash" }]} />

      <div className="page-header">
        <div className="page-title">
          <h1>Trash</h1>
          <span className="page-subtitle">
            Files past {RETENTION_DAYS} days are deleted permanently.
          </span>
        </div>
      </div>

      {loading && <p className="text-muted">Loading trash…</p>}
      {error && <p className="field-error">{error}</p>}

      {!loading && !error && items.length === 0 && (
        <div className="empty">
          <div className="empty-title">Trash is empty</div>
          <div className="text-small text-muted">
            Deleted files appear here and are kept for {RETENTION_DAYS} days before being purged.
          </div>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th className="cell-right">Size</th>
                <th>Deleted</th>
                <th>Days left</th>
                <th className="cell-actions"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => {
                const left = daysLeft(f.deleted_at);
                const tone =
                  left <= 3
                    ? "var(--color-danger)"
                    : left <= 7
                      ? "var(--color-warning)"
                      : "var(--color-muted)";
                return (
                  <tr key={f.id}>
                    <td>
                      <span className="row row-3">
                        <FileGeneric size={16} className="text-muted" />
                        <span className="filename" title={f.original_filename}>
                          {f.original_filename}
                        </span>
                      </span>
                    </td>
                    <td className="cell-right text-mono text-small">{formatBytes(f.size_bytes)}</td>
                    <td className="cell-muted text-small">{formatDateTime(f.deleted_at)}</td>
                    <td className="text-small" style={{ color: tone }}>
                      {left} days
                    </td>
                    <td className="cell-actions">
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() => onRestore(f)}
                        title="Restore"
                        aria-label="Restore"
                      >
                        <RotateCcw size={14} />
                      </button>
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() => onHardDelete(f)}
                        title="Delete now"
                        aria-label="Delete now"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
