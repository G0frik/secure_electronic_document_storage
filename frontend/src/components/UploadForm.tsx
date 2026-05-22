import { FormEvent, useRef, useState } from "react";
import { AxiosError } from "axios";
import { uploadFile } from "@/api/files";
import { Folder } from "@/api/folders";

interface Props {
  onUploaded: () => void;
  folders: Folder[];
  currentFolderId: string | null;
  onFolderChange: (folderId: string | null) => void;
}

export default function UploadForm({
  onUploaded,
  folders,
  currentFolderId,
  onFolderChange,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const file = inputRef.current?.files?.[0];
    if (!file) {
      setError("Pick a file first.");
      return;
    }
    setBusy(true);
    setProgress(0);
    try {
      await uploadFile(file, {
        onProgress: setProgress,
        folderId: currentFolderId,
      });
      if (inputRef.current) inputRef.current.value = "";
      onUploaded();
    } catch (err) {
      const ax = err as AxiosError<{
        error?: string;
        message?: string;
        used_bytes?: number;
        quota_bytes?: number;
        available_bytes?: number;
      }>;
      if (ax.response?.status === 413) {
        const body = ax.response?.data;
        if (body?.error === "quota_exceeded") {
          const avail = body.available_bytes ?? 0;
          setError(
            `Quota exceeded — only ${Math.max(0, Math.round(avail / 1024))} KB left. ` +
              "Delete some files (and empty Trash) to free space.",
          );
        } else {
          setError("File is too large (50 MB max).");
        }
      } else {
        setError(ax.response?.data?.message ?? "Upload failed.");
      }
    } finally {
      setBusy(false);
      setTimeout(() => setProgress(null), 1500);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ marginBottom: "1.5rem" }}>
      <input ref={inputRef} type="file" disabled={busy} />
      <label style={{ marginLeft: "0.5rem" }}>
        into{" "}
        <select
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
      <button type="submit" disabled={busy} style={{ marginLeft: "0.5rem" }}>
        {busy ? "Uploading…" : "Upload"}
      </button>
      {progress !== null && (
        <progress value={progress} max={100} style={{ marginLeft: "1rem", width: "200px" }} />
      )}
      {error && (
        <p className="status-fail" style={{ marginTop: "0.5rem" }}>
          {error}
        </p>
      )}
    </form>
  );
}
