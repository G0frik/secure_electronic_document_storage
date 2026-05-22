import { ChangeEvent, DragEvent, useCallback, useRef, useState } from "react";
import { AxiosError } from "axios";
import { uploadFile } from "@/api/files";
import { Folder } from "@/api/folders";
import { UploadCloud } from "@/components/icons";

interface Props {
  /** Called after a successful upload so the parent can refresh listings. */
  onUploaded: () => void;
  /** Folders for the placement dropdown — root + every owned folder. */
  folders: Folder[];
  /** Currently selected destination folder, or null for root. */
  currentFolderId: string | null;
  onFolderChange: (folderId: string | null) => void;
}

/**
 * Drag-and-drop upload zone. Clicking the zone or pressing Browse opens
 * the native file picker. Dropping a file (or files) onto the zone uploads
 * them sequentially.
 *
 * Wraps the same `uploadFile()` API as the old UploadForm — the only
 * differences are the drop target + the visual treatment. Quota / 413
 * handling is identical.
 */
export default function DropzoneUpload({
  onUploaded,
  folders,
  currentFolderId,
  onFolderChange,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      setError(null);
      setBusy(true);
      try {
        for (const file of list) {
          setProgress(0);
          await uploadFile(file, {
            onProgress: setProgress,
            folderId: currentFolderId,
          });
        }
        if (inputRef.current) inputRef.current.value = "";
        onUploaded();
      } catch (err) {
        const ax = err as AxiosError<{
          error?: string;
          message?: string;
          available_bytes?: number;
        }>;
        if (ax.response?.status === 413) {
          const body = ax.response?.data;
          if (body?.error === "quota_exceeded") {
            const avail = body.available_bytes ?? 0;
            setError(
              `Quota exceeded — only ${Math.max(
                0,
                Math.round(avail / 1024),
              )} KB left. Delete some files (and empty Trash) to free space.`,
            );
          } else {
            setError("File is too large (50 MB max).");
          }
        } else {
          setError(ax.response?.data?.message ?? "Upload failed.");
        }
      } finally {
        setBusy(false);
        setTimeout(() => setProgress(null), 1200);
      }
    },
    [currentFolderId, onUploaded],
  );

  function onInputChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files) handleFiles(e.target.files);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files) handleFiles(e.dataTransfer.files);
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (!dragging) setDragging(true);
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    // Only flip off when the cursor leaves the dropzone entirely, not
    // when it crosses an internal child element.
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setDragging(false);
  }

  return (
    <div className="stack stack-3" style={{ marginBottom: "var(--space-5)" }}>
      <div
        className={`dropzone${dragging ? " is-dragging" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        role="button"
        tabIndex={0}
        aria-label="Upload file by dropping or clicking to browse"
      >
        <UploadCloud size={28} className="dropzone-icon" />
        <div className="dropzone-title">
          {dragging ? "Release to upload" : "Drop files here, or click to browse"}
        </div>
        <div className="dropzone-hint">
          Up to 50&nbsp;MB per file. Encrypted at rest with AES-256-GCM.
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          onChange={onInputChange}
          disabled={busy}
          style={{ display: "none" }}
        />
      </div>

      <div className="row row-3" style={{ flexWrap: "wrap" }}>
        <label className="row row-2 text-small text-muted">
          Upload into:
          <select
            className="select"
            style={{ width: "auto", height: "32px" }}
            value={currentFolderId ?? ""}
            onChange={(e) => onFolderChange(e.target.value || null)}
            disabled={busy}
          >
            <option value="">— root —</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>

        {progress !== null && (
          <span className="row row-2 text-small text-muted">
            <progress value={progress} max={100} style={{ width: 140 }} />
            <span className="text-mono">{progress}%</span>
          </span>
        )}
      </div>

      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
