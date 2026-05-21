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

interface Props {
  fileId: string;
  fileLabel: string;
  onClose: () => void;
  /** Parent refresh hook — fires after upload-new-version + after delete. */
  onChanged?: () => void;
}

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
    evt.target.value = ""; // allow re-picking the same file
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
        setError("Quota exceeded — free up space before uploading a new version.");
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
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white",
          padding: "1.5rem",
          width: "min(48rem, 90vw)",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: "0.75rem",
          }}
        >
          <h3 style={{ margin: 0 }}>
            Versions · <code>{fileLabel}</code>
          </h3>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.4rem 0.75rem",
              background: "#f6f8fa",
              border: "1px solid #d0d7de",
              borderRadius: "6px",
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
          >
            <input
              type="file"
              onChange={onUpload}
              disabled={busy}
              style={{ display: "none" }}
            />
            Upload new version…
          </label>
          {busy && progress > 0 && (
            <span style={{ marginLeft: "0.75rem", color: "#6e7781" }}>
              Uploading… {progress}%
            </span>
          )}
        </div>

        {error && <p className="status-fail">{error}</p>}

        <div
          style={{
            flex: 1,
            overflow: "auto",
            border: "1px solid #eaeef2",
            borderRadius: "4px",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ background: "#f6f8fa" }}>
              <tr style={{ textAlign: "left" }}>
                <th style={{ padding: "0.5rem" }}>#</th>
                <th style={{ padding: "0.5rem" }}>Filename</th>
                <th style={{ padding: "0.5rem", textAlign: "right" }}>Size</th>
                <th style={{ padding: "0.5rem" }}>Uploaded</th>
                <th style={{ padding: "0.5rem" }}></th>
              </tr>
            </thead>
            <tbody>
              {versions.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: "0.75rem", color: "#6e7781" }}>
                    No versions yet.
                  </td>
                </tr>
              )}
              {versions.map((v) => (
                <tr
                  key={v.version_number}
                  style={{
                    borderTop: "1px solid #eaeef2",
                    background: v.is_current ? "#f0f7ff" : undefined,
                  }}
                >
                  <td style={{ padding: "0.5rem" }}>
                    v{v.version_number}
                    {v.is_current && (
                      <span
                        style={{
                          marginLeft: "0.4rem",
                          padding: "0 0.4rem",
                          fontSize: "0.75em",
                          background: "#0969da",
                          color: "white",
                          borderRadius: "10px",
                        }}
                      >
                        current
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "0.5rem" }}>
                    <code>{v.original_filename}</code>
                  </td>
                  <td style={{ padding: "0.5rem", textAlign: "right" }}>
                    {formatBytes(v.size_bytes)}
                  </td>
                  <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                    {v.uploaded_at ? formatDateTime(v.uploaded_at) : "—"}
                  </td>
                  <td style={{ padding: "0.5rem" }}>
                    <button onClick={() => onDownload(v)}>Download</button>
                    {!v.is_current && (
                      <button
                        onClick={() => onDelete(v)}
                        style={{ marginLeft: "0.25rem" }}
                        title="Permanently delete this version"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
