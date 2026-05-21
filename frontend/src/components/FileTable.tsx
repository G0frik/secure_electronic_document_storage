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
import VersionsDialog from "@/components/VersionsDialog";
import { Tier } from "@/api/tierOverrides";
import { reclassifyFile } from "@/api/admin";
import { useAuth } from "@/state/auth";
import { useToast } from "@/state/toast";
import {
  ArrowUpDown,
  Download,
  Eye,
  FileCode,
  FileGeneric,
  FileImage,
  FileSpreadsheet,
  FileText,
  History,
  MoreHorizontal,
  RefreshCw,
  Share2,
  Tag,
  Trash2,
} from "@/components/icons";

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

/**
 * Pick a Lucide icon based on the file's mime type / extension. Falls back
 * to a generic file icon. Used purely for visual differentiation in the
 * Name column — semantic meaning still comes from the filename.
 */
function iconForFile(file: StoredFile) {
  const mime = (file.mime_type || "").toLowerCase();
  const name = (file.original_filename || "").toLowerCase();
  if (mime.startsWith("image/")) return FileImage;
  if (
    mime.includes("spreadsheet") ||
    name.endsWith(".csv") ||
    name.endsWith(".tsv") ||
    name.endsWith(".xlsx")
  ) {
    return FileSpreadsheet;
  }
  if (
    mime.startsWith("text/") ||
    mime === "application/pdf" ||
    name.endsWith(".pdf") ||
    name.endsWith(".docx") ||
    name.endsWith(".md") ||
    name.endsWith(".txt")
  ) {
    return FileText;
  }
  if (
    name.endsWith(".json") ||
    name.endsWith(".yaml") ||
    name.endsWith(".yml") ||
    name.endsWith(".sh") ||
    name.endsWith(".py") ||
    name.endsWith(".ts") ||
    name.endsWith(".js")
  ) {
    return FileCode;
  }
  return FileGeneric;
}

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
  const toast = useToast();
  const isAdmin = user?.role === "admin";
  const [classifications, setClassifications] = useState<Record<string, ClassificationResult>>({});
  const [shareTarget, setShareTarget] = useState<StoredFile | null>(null);
  const [tagsTarget, setTagsTarget] = useState<StoredFile | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<StoredFile | null>(null);
  const [previewTarget, setPreviewTarget] = useState<StoredFile | null>(null);
  const [versionsTarget, setVersionsTarget] = useState<StoredFile | null>(null);
  const [openMenuFor, setOpenMenuFor] = useState<string | null>(null);
  const menuWrapperRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | null>(null);

  // Phase 4 classification polling — preserved verbatim from the original
  // FileTable. Only the visual treatment around it changed.
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

  // Close the row action popover on outside click.
  useEffect(() => {
    if (!openMenuFor) return;
    function onClick(e: MouseEvent) {
      if (
        menuWrapperRef.current &&
        !menuWrapperRef.current.contains(e.target as Node)
      ) {
        setOpenMenuFor(null);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [openMenuFor]);

  async function onDownload(file: StoredFile) {
    try {
      await downloadFile(file);
    } catch (err) {
      if (err instanceof AccessDeniedError) {
        toast.error(
          `Access denied${err.tier ? ` (tier ${err.tier})` : ""}`,
          `${err.message} (reason: ${err.reason})`,
        );
      } else {
        toast.error("Download failed", "See browser console for details.");
        console.error(err);
      }
    }
  }

  async function onSoftDelete(file: StoredFile) {
    if (
      !window.confirm(
        `Move "${file.original_filename}" to trash? You can restore it within 30 days.`,
      )
    ) {
      return;
    }
    try {
      await softDeleteFile(file.id);
      toast.success(`Moved "${file.original_filename}" to trash`);
      onDeleted?.();
    } catch (err) {
      console.error(err);
      toast.error("Delete failed", "See browser console for details.");
    }
  }

  async function onReclassify(file: StoredFile) {
    if (!window.confirm(`Re-run the classifier on "${file.original_filename}"?`)) return;
    try {
      await reclassifyFile(file.id);
      toast.info("Reclassification queued", "Tier will update once it completes.");
      setClassifications((prev) => {
        const next = { ...prev };
        delete next[file.id];
        return next;
      });
    } catch (err) {
      console.error(err);
      toast.error("Reclassify failed", "See browser console for details.");
    }
  }

  if (files.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No files here yet</div>
        <div className="text-small text-muted">
          Drop a file on the upload zone above to get started.
        </div>
      </div>
    );
  }

  const lastPage = Math.max(1, Math.ceil(total / perPage));

  return (
    <>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>
                <span className="row row-2">
                  Name <ArrowUpDown size={12} />
                </span>
              </th>
              <th>Tier</th>
              <th>Type</th>
              <th className="cell-right">Size</th>
              <th>Uploaded</th>
              <th className="cell-actions"></th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => {
              const Icon = iconForFile(f);
              const cls = classifications[f.id];
              return (
                <tr key={f.id}>
                  <td>
                    <span className="row row-3">
                      <Icon size={16} className="text-muted" aria-hidden="true" />
                      <span className="filename">{f.original_filename}</span>
                      {f.current_version && f.current_version > 1 && (
                        <span className="text-mono text-small text-muted">
                          v{f.current_version}
                        </span>
                      )}
                    </span>
                  </td>
                  <td>
                    <TierBadge classification={cls} />
                  </td>
                  <td className="cell-muted text-mono text-small">
                    {f.mime_type}
                  </td>
                  <td className="cell-right text-mono text-small">
                    {formatBytes(f.size_bytes)}
                  </td>
                  <td className="cell-muted text-small">
                    {formatDateTime(f.uploaded_at)}
                  </td>
                  <td className="cell-actions">
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => onDownload(f)}
                      title="Download"
                      aria-label="Download"
                    >
                      <Download size={14} />
                    </button>
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => setPreviewTarget(f)}
                      title="Preview"
                      aria-label="Preview"
                    >
                      <Eye size={14} />
                    </button>

                    <div
                      ref={openMenuFor === f.id ? menuWrapperRef : undefined}
                      style={{ position: "relative", display: "inline-block" }}
                    >
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() =>
                          setOpenMenuFor(openMenuFor === f.id ? null : f.id)
                        }
                        aria-haspopup="menu"
                        aria-expanded={openMenuFor === f.id}
                        title="More actions"
                      >
                        <MoreHorizontal size={14} />
                      </button>
                      {openMenuFor === f.id && (
                        <div
                          className="popover"
                          role="menu"
                          style={{
                            position: "absolute",
                            top: "calc(100% + 4px)",
                            right: 0,
                            minWidth: 200,
                            padding: "var(--space-1) 0",
                            zIndex: 50,
                          }}
                        >
                          {showShare && (
                            <RowMenuItem
                              icon={<Share2 size={14} />}
                              label="Share…"
                              onClick={() => {
                                setOpenMenuFor(null);
                                setShareTarget(f);
                              }}
                            />
                          )}
                          {showDelete && (
                            <RowMenuItem
                              icon={<Tag size={14} />}
                              label="Tags…"
                              onClick={() => {
                                setOpenMenuFor(null);
                                setTagsTarget(f);
                              }}
                            />
                          )}
                          {showDelete && (
                            <RowMenuItem
                              icon={<History size={14} />}
                              label={
                                f.current_version && f.current_version > 1
                                  ? `Versions (v${f.current_version})`
                                  : "Versions…"
                              }
                              onClick={() => {
                                setOpenMenuFor(null);
                                setVersionsTarget(f);
                              }}
                            />
                          )}
                          {showDelete && cls?.final_tier && (
                            <RowMenuItem
                              icon={<ArrowUpDown size={14} />}
                              label="Request tier override…"
                              onClick={() => {
                                setOpenMenuFor(null);
                                setOverrideTarget(f);
                              }}
                            />
                          )}
                          {isAdmin && (
                            <RowMenuItem
                              icon={<RefreshCw size={14} />}
                              label="Re-run classifier"
                              onClick={() => {
                                setOpenMenuFor(null);
                                onReclassify(f);
                              }}
                            />
                          )}
                          {showDelete && (
                            <>
                              <div className="divider" style={{ margin: "var(--space-1) 0" }} />
                              <RowMenuItem
                                icon={<Trash2 size={14} />}
                                label="Move to trash"
                                onClick={() => {
                                  setOpenMenuFor(null);
                                  onSoftDelete(f);
                                }}
                                danger
                              />
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {lastPage > 1 && (
        <div className="row row-3" style={{ marginTop: "var(--space-4)" }}>
          <button
            className="btn btn-sm"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            ← Prev
          </button>
          <span className="text-small text-muted">
            Page {page} of {lastPage} ({total} total)
          </span>
          <button
            className="btn btn-sm"
            disabled={page >= lastPage}
            onClick={() => onPageChange(page + 1)}
          >
            Next →
          </button>
        </div>
      )}

      {shareTarget && (
        <ShareDialog
          targetType="file"
          targetId={shareTarget.id}
          targetLabel={shareTarget.original_filename}
          onClose={() => setShareTarget(null)}
          onShared={() => {
            /* Toast wiring lands in Batch D. */
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

      {versionsTarget && (
        <VersionsDialog
          fileId={versionsTarget.id}
          fileLabel={versionsTarget.original_filename}
          onClose={() => setVersionsTarget(null)}
          onChanged={() => onDeleted?.()}
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
            /* Toast wiring lands in Batch D. */
          }}
        />
      )}
    </>
  );
}

function RowMenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        width: "100%",
        padding: "var(--space-2) var(--space-4)",
        background: "transparent",
        border: "none",
        textAlign: "left",
        font: "inherit",
        color: danger ? "var(--color-danger)" : "var(--color-ink)",
        cursor: "pointer",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.background = "var(--color-bg)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {icon}
      {label}
    </button>
  );
}
