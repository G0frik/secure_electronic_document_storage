import { ChangeEvent, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  deleteFileVersion,
  downloadFileVersion,
  FileVersionEntry,
  listFileVersions,
  uploadFileVersion,
} from "@/api/files";
import { formatBytes, formatDateTime } from "@/utils/format";
import Drawer from "@/components/Drawer";
import { Download, Trash2, Upload } from "@/components/icons";

interface Props {
  fileId: string;
  fileLabel: string;
  onClose: () => void;
  /** Parent refresh hook — fires after upload-new-version + after delete. */
  onChanged?: () => void;
}

/**
 * Versions drawer.
 *
 * Lists current + historical versions of a file. Upload-new-version is a
 * styled file-input. Each historical version row has Download + Delete
 * icon buttons; current row only has Download (and shows the "current"
 * pill). The reaper purges history older than 30 days regardless.
 */
export default function VersionsDialog({
  fileId,
  fileLabel,
  onClose,
  onChanged,
}: Props) {
  const [versions, setVersions] = useState<FileVersionEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  async function refresh() {
    try {
      const items = await listFileVersions(fileId);
      setVersions(items);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Could not load versions.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId]);

  async function onUpload(evt: ChangeEvent<HTMLInputElement>) {
    const file = evt.target.files?.[0];
    evt.target.value = "";
    if (!file) return;
    setError(null);
    setProgress(0);
    setBusy(true);
    try {
      await uploadFileVersion(fileId, file, {
        onProgress: (p) => setProgress(p),
      });
      await refresh();
      onChanged?.();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string; error?: string }>;
      if (ax.response?.data?.error === "quota_exceeded") {
        setError(
          "Quota exceeded — free up space before uploading a new version.",
        );
      } else {
        setError(ax.response?.data?.message ?? "Upload failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function onDownload(v: FileVersionEntry) {
    setError(null);
    try {
      await downloadFileVersion(fileId, v.version_number, v.original_filename);
    } catch (err) {
      setError("Download failed — see console.");
      console.error(err);
    }
  }

  async function onDelete(v: FileVersionEntry) {
    if (
      !window.confirm(
        `Permanently delete version ${v.version_number} (${formatBytes(v.size_bytes)})? ` +
          "This cannot be undone.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      await deleteFileVersion(fileId, v.version_number);
      await refresh();
      onChanged?.();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Delete failed.");
    }
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title="Versions"
      subtitle={<span className="filename">{fileLabel}</span>}
      footer={
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      }
    >
      <div className="row row-3" style={{ flexWrap: "wrap" }}>
        <label
          className="btn btn-primary"
          style={{ cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1 }}
        >
          <Upload size={14} />
          {busy ? `Uploading… ${progress}%` : "Upload new version"}
          <input
            type="file"
            onChange={onUpload}
            disabled={busy}
            style={{ display: "none" }}
          />
        </label>
        <span className="text-small text-muted">
          The reaper purges history older than 30 days.
        </span>
      </div>

      {error && <p className="field-error">{error}</p>}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Filename</th>
              <th className="cell-right">Size</th>
              <th>Uploaded</th>
              <th className="cell-actions"></th>
            </tr>
          </thead>
          <tbody>
            {versions.length === 0 && (
              <tr>
                <td colSpan={5} className="text-muted">
                  No versions yet.
                </td>
              </tr>
            )}
            {versions.map((v) => (
              <tr key={v.version_number}>
                <td>
                  <span className="row row-2 text-mono text-small">
                    v{v.version_number}
                    {v.is_current && (
                      <span className="badge badge-internal">current</span>
                    )}
                  </span>
                </td>
                <td className="filename">{v.original_filename}</td>
                <td className="cell-right text-mono text-small">
                  {formatBytes(v.size_bytes)}
                </td>
                <td className="cell-muted text-small">
                  {v.uploaded_at ? formatDateTime(v.uploaded_at) : "—"}
                </td>
                <td className="cell-actions">
                  <button
                    className="btn btn-ghost btn-icon btn-sm"
                    onClick={() => onDownload(v)}
                    title="Download"
                    aria-label="Download"
                  >
                    <Download size={14} />
                  </button>
                  {!v.is_current && (
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => onDelete(v)}
                      title="Delete this version"
                      aria-label="Delete this version"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Drawer>
  );
}
