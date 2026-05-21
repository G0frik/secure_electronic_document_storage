import { useEffect, useRef, useState } from "react";
import {
  AccessDeniedError,
  ClassificationResult,
  downloadFile,
  fetchClassification,
  softDeleteFile,
  StoredFile,
} from "@/api/files";
import { formatBytes, formatDateTime } from "@/utils/format";
import TierBadge from "@/components/TierBadge";
import ShareDialog from "@/components/ShareDialog";
import TagsDialog from "@/components/TagsDialog";
import OverrideRequestDialog from "@/components/OverrideRequestDialog";
import PreviewDialog from "@/components/PreviewDialog";
import { Tier } from "@/api/tierOverrides";
import { reclassifyFile } from "@/api/admin";
import { useAuth } from "@/state/auth";

interface Props {
  files: StoredFile[];
  page: number;
  perPage: number;
  total: number;
  onPageChange: (newPage: number) => void;
  /** Owner can share their own files. Hide button when this is false (Shared-with-me view). */
  showShare?: boolean;
  /** Owner can trash their own files. Hide when this is false (Shared-with-me view). */
  showDelete?: boolean;
  /** Called after a file is soft-deleted so the parent page can refresh. */
  onDeleted?: () => void;
}

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["completed", "failed", "missing"]);

export default function FileTable({
  files,
  page,
  perPage,
  total,
  onPageChange,
  showShare = true,
  showDelete = true,
  onDeleted,
}: Props) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [classifications, setClassifications] = useState<Record<string, ClassificationResult>>({});
  const [shareTarget, setShareTarget] = useState<StoredFile | null>(null);
  const [tagsTarget, setTagsTarget] = useState<StoredFile | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<StoredFile | null>(null);
  const [previewTarget, setPreviewTarget] = useState<StoredFile | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function pollOnce() {
      const pendingIds = files
        .map((f) => f.id)
        .filter((id) => {
          const c = classifications[id];
          return !c || !TERMINAL_STATUSES.has(c.status);
        });

      const results = await Promise.allSettled(pendingIds.map((id) => fetchClassification(id)));
      if (cancelled) return;
      const updates: Record<string, ClassificationResult> = {};
      results.forEach((r, idx) => {
        if (r.status === "fulfilled") updates[pendingIds[idx]!] = r.value;
      });
      if (Object.keys(updates).length > 0) {
        setClassifications((prev) => ({ ...prev, ...updates }));
      }

      const stillPending = files.some((f) => {
        const c = { ...classifications, ...updates }[f.id];
        return !c || !TERMINAL_STATUSES.has(c.status);
      });
      if (stillPending && !cancelled) {
        timerRef.current = window.setTimeout(pollOnce, POLL_INTERVAL_MS);
      }
    }

    if (files.length > 0) {
      pollOnce();
    }

    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

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
            <th style={{ padding: "0.5rem" }}>Tier</th>
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
              <td style={{ padding: "0.5rem" }}>
                <TierBadge classification={classifications[f.id]} />
              </td>
              <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                <code>{f.mime_type}</code>
              </td>
              <td style={{ padding: "0.5rem", textAlign: "right" }}>{formatBytes(f.size_bytes)}</td>
              <td style={{ padding: "0.5rem", color: "#6e7781" }}>
                {formatDateTime(f.uploaded_at)}
              </td>
              <td style={{ padding: "0.5rem" }}>
                <button
                  onClick={async () => {
                    try {
                      await downloadFile(f);
                    } catch (err) {
                      if (err instanceof AccessDeniedError) {
                        alert(
                          `Access denied${err.tier ? ` (tier: ${err.tier})` : ""}:\n` +
                            `${err.message}\n\nreason: ${err.reason}`,
                        );
                      } else {
                        alert("Download failed — see console.");
                        console.error(err);
                      }
                    }
                  }}
                >
                  Download
                </button>
                <button
                  onClick={() => setPreviewTarget(f)}
                  style={{ marginLeft: "0.25rem" }}
                  title="Preview the file's text content"
                >
                  Preview…
                </button>
                {showShare && (
                  <button
                    onClick={() => setShareTarget(f)}
                    style={{ marginLeft: "0.25rem" }}
                  >
                    Share…
                  </button>
                )}
                {showDelete && (
                  <button
                    onClick={() => setTagsTarget(f)}
                    style={{ marginLeft: "0.25rem" }}
                  >
                    Tags…
                  </button>
                )}
                {showDelete && classifications[f.id]?.final_tier && (
                  <button
                    onClick={() => setOverrideTarget(f)}
                    style={{ marginLeft: "0.25rem" }}
                    title="Request a tier change from an admin"
                  >
                    Override…
                  </button>
                )}
                {isAdmin && (
                  <button
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `Re-run the classifier on "${f.original_filename}"?`,
                        )
                      ) {
                        return;
                      }
                      try {
                        await reclassifyFile(f.id);
                        // Wipe cached classification for this file so the
                        // table starts polling again.
                        setClassifications((prev) => {
                          const next = { ...prev };
                          delete next[f.id];
                          return next;
                        });
                      } catch (err) {
                        console.error(err);
                        alert("Reclassify failed — see console.");
                      }
                    }}
                    style={{ marginLeft: "0.25rem" }}
                    title="Admin: re-run the classifier"
                  >
                    Reclassify
                  </button>
                )}
                {showDelete && (
                  <button
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `Move "${f.original_filename}" to trash? You can restore it within 30 days.`,
                        )
                      ) {
                        return;
                      }
                      try {
                        await softDeleteFile(f.id);
                        onDeleted?.();
                      } catch (err) {
                        console.error(err);
                        alert("Delete failed — see console.");
                      }
                    }}
                    style={{ marginLeft: "0.25rem" }}
                  >
                    Delete
                  </button>
                )}
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

      {shareTarget && (
        <ShareDialog
          targetType="file"
          targetId={shareTarget.id}
          targetLabel={shareTarget.original_filename}
          onClose={() => setShareTarget(null)}
          onShared={() => {
            /* Could surface a toast here. */
          }}
        />
      )}

      {tagsTarget && (
        <TagsDialog
          fileId={tagsTarget.id}
          fileLabel={tagsTarget.original_filename}
          onClose={() => setTagsTarget(null)}
        />
      )}

      {previewTarget && (
        <PreviewDialog
          fileId={previewTarget.id}
          fileLabel={previewTarget.original_filename}
          onClose={() => setPreviewTarget(null)}
        />
      )}

      {overrideTarget && (
        <OverrideRequestDialog
          fileId={overrideTarget.id}
          fileLabel={overrideTarget.original_filename}
          currentTier={
            (classifications[overrideTarget.id]?.final_tier as Tier | null) ?? null
          }
          onClose={() => setOverrideTarget(null)}
          onSubmitted={() => {
            /* Could surface a toast here. */
          }}
        />
      )}
    </>
  );
}
