import { downloadFile, StoredFile } from "@/api/files";
import { formatBytes, formatDateTime } from "@/utils/format";

interface Props {
  files: StoredFile[];
  page: number;
  perPage: number;
  total: number;
  onPageChange: (newPage: number) => void;
}

export default function FileTable({ files, page, perPage, total, onPageChange }: Props) {
  if (files.length === 0) {
    return <p className="status-pending">No files yet — upload one above.</p>;
  }

  const lastPage = Math.max(1, Math.ceil(total / perPage));

  return (
    <>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.5rem" }}>Name</th>
            <th style={{ padding: "0.5rem" }}>Type</th>
            <th style={{ padding: "0.5rem", textAlign: "right" }}>Size</th>
            <th style={{ padding: "0.5rem" }}>Uploaded</th>
            <th style={{ padding: "0.5rem" }}></th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.5rem" }}>{f.original_filename}</td>
              <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                <code>{f.mime_type}</code>
              </td>
              <td style={{ padding: "0.5rem", textAlign: "right" }}>{formatBytes(f.size_bytes)}</td>
              <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                {formatDateTime(f.uploaded_at)}
              </td>
              <td style={{ padding: "0.5rem" }}>
                <button onClick={() => downloadFile(f)}>Download</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {lastPage > 1 && (
        <p style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
            ← Prev
          </button>
          <span style={{ color: "#6e7781" }}>
            Page {page} of {lastPage} ({total} total)
          </span>
          <button disabled={page >= lastPage} onClick={() => onPageChange(page + 1)}>
            Next →
          </button>
        </p>
      )}
    </>
  );
}
