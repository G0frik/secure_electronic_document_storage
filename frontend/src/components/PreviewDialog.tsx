import { useEffect, useState } from "react";
import {
  AccessDeniedError,
  fetchPreview,
  PreviewExtractionError,
  PreviewResponse,
  UnsupportedPreviewError,
} from "@/api/files";
import { formatBytes } from "@/utils/format";
import { Close } from "@/components/icons";

interface Props {
  fileId: string;
  fileLabel: string;
  onClose: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; payload: PreviewResponse }
  | { kind: "unsupported"; message: string }
  | { kind: "extraction_failed"; message: string }
  | { kind: "denied"; message: string }
  | { kind: "error"; message: string };

/**
 * Centered preview modal.
 *
 * Kept as a centered modal rather than a drawer because file-viewer
 * convention is centered + wide. Uses the `.modal` class for placement +
 * shadow. Click outside or the X button closes it.
 */
export default function PreviewDialog({
  fileId,
  fileLabel,
  onClose,
}: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchPreview(fileId)
      .then((payload) => {
        if (!cancelled) setState({ kind: "ready", payload });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof UnsupportedPreviewError) {
          setState({ kind: "unsupported", message: err.message });
        } else if (err instanceof PreviewExtractionError) {
          setState({ kind: "extraction_failed", message: err.message });
        } else if (err instanceof AccessDeniedError) {
          setState({
            kind: "denied",
            message: `${err.message} (reason: ${err.reason})`,
          });
        } else {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Preview failed.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fileId]);

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">
        <header className="drawer-header">
          <div>
            <div className="drawer-title">Preview</div>
            <div className="drawer-subtitle filename">{fileLabel}</div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-icon btn-sm"
            onClick={onClose}
            aria-label="Close"
          >
            <Close size={16} />
          </button>
        </header>

        <div
          className="drawer-body"
          style={{ padding: 0, display: "flex", flexDirection: "column" }}
        >
          {state.kind === "ready" && (
            <div
              style={{
                padding: "var(--space-2) var(--space-5)",
                borderBottom: "1px solid var(--color-line)",
              }}
            >
              <PreviewMeta payload={state.payload} />
            </div>
          )}

          <div
            style={{
              flex: 1,
              overflow: "auto",
              background: "var(--color-surface-2)",
              padding: "var(--space-4) var(--space-5)",
            }}
          >
            {state.kind === "loading" && (
              <p className="text-muted">Loading preview…</p>
            )}
            {state.kind === "ready" && (
              <pre
                style={{
                  margin: 0,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.875rem",
                  lineHeight: 1.55,
                  color: "var(--color-ink)",
                }}
              >
                {state.payload.text || "(empty document)"}
              </pre>
            )}
            {state.kind === "unsupported" && (
              <p className="text-muted">{state.message}</p>
            )}
            {state.kind === "extraction_failed" && (
              <p className="field-error">{state.message}</p>
            )}
            {state.kind === "denied" && (
              <p className="field-error">{state.message}</p>
            )}
            {state.kind === "error" && (
              <p className="field-error">{state.message}</p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function PreviewMeta({ payload }: { payload: PreviewResponse }) {
  return (
    <p className="text-small text-muted" style={{ margin: 0 }}>
      <span className="text-mono">{payload.extractor.toUpperCase()}</span> ·{" "}
      {formatBytes(payload.size_bytes)} ·{" "}
      {payload.truncated
        ? `showing first ${formatBytes(payload.preview_bytes)} of ${formatBytes(
            payload.original_bytes,
          )} extracted text`
        : `${formatBytes(payload.preview_bytes)} of extracted text`}
    </p>
  );
}
