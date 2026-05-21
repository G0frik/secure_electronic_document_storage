import { useEffect, useState } from "react";
import {
  AccessDeniedError,
  fetchPreview,
  PreviewExtractionError,
  PreviewResponse,
  UnsupportedPreviewError,
} from "@/api/files";
import { formatBytes } from "@/utils/format";

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

export default function PreviewDialog({ fileId, fileLabel, onClose }: Props) {
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
          width: "min(64rem, 90vw)",
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
            Preview · <code>{fileLabel}</code>
          </h3>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>

        {state.kind === "ready" && (
          <PreviewMeta payload={state.payload} />
        )}

        <div
          style={{
            flex: 1,
            overflow: "auto",
            border: "1px solid #eaeef2",
            borderRadius: "4px",
            background: "#f6f8fa",
            padding: "1rem",
            marginTop: "0.5rem",
          }}
        >
          {state.kind === "loading" && (
            <p className="status-pending">Loading preview…</p>
          )}
          {state.kind === "ready" && (
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.85rem",
                lineHeight: 1.5,
              }}
            >
              {state.payload.text || "(empty document)"}
            </pre>
          )}
          {state.kind === "unsupported" && (
            <p className="status-pending">{state.message}</p>
          )}
          {state.kind === "extraction_failed" && (
            <p className="status-fail">{state.message}</p>
          )}
          {state.kind === "denied" && (
            <p className="status-fail">{state.message}</p>
          )}
          {state.kind === "error" && (
            <p className="status-fail">{state.message}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewMeta({ payload }: { payload: PreviewResponse }) {
  return (
    <p style={{ margin: 0, color: "#6e7781", fontSize: "0.85em" }}>
      {payload.extractor.toUpperCase()} · {formatBytes(payload.size_bytes)} ·{" "}
      {payload.truncated
        ? `showing first ${formatBytes(payload.preview_bytes)} of ${formatBytes(
            payload.original_bytes,
          )} extracted text`
        : `${formatBytes(payload.preview_bytes)} of extracted text`}
    </p>
  );
}
