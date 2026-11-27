import { useMemo, useState } from "react";
import DocumentView from "@/components/DocumentView";
import { decodeB64, type DocPayload } from "@/api/playground";

type View = "document" | "full" | "visible";

/** A document as a reader sees it, plus what the classifier reads (full) and what a reader sees (visible). */
export default function DocPreview({ doc, note }: { doc: DocPayload; note?: string }) {
  const ext = doc.filename.split(".").pop()?.toLowerCase() ?? "";
  const kind = ext === "pdf" ? "pdf" : ext === "docx" ? "docx" : null;
  const [view, setView] = useState<View>(kind ? "document" : "full");
  const data = useMemo(() => decodeB64(doc.data_b64), [doc.data_b64]);
  const hidden = doc.views.full !== doc.views.visible;
  const shown: View = !kind && view === "document" ? "full" : view;

  return (
    <div className="stack stack-2">
      <div className="row row-between" style={{ gap: "var(--space-3)" }}>
        <span className="text-small text-muted">
          <span className="text-mono">{doc.filename}</span>
          {note ? ` · ${note}` : ""}
        </span>
        <div className="preview-tabs" role="tablist" aria-label="Preview mode">
          {kind && (
            <button
              type="button"
              role="tab"
              aria-selected={shown === "document"}
              className="btn btn-sm btn-ghost"
              onClick={() => setView("document")}
            >
              Document
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={shown === "full"}
            className="btn btn-sm btn-ghost"
            onClick={() => setView("full")}
          >
            Classifier reads
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={shown === "visible"}
            className="btn btn-sm btn-ghost"
            onClick={() => setView("visible")}
          >
            Reader sees
          </button>
        </div>
      </div>
      {hidden && (
        <p className="text-small" style={{ margin: 0, color: "var(--color-warning)" }}>
          This document contains text a reader does not see (
          {doc.views.full.length - doc.views.visible.length > 0
            ? `${doc.views.full.length - doc.views.visible.length} more characters`
            : "different text"}{" "}
          in what the classifier reads).
        </p>
      )}
      <div className="pg-preview">
        {shown === "document" && kind && <DocumentView data={data} kind={kind} />}
        {shown !== "document" && (
          <pre className="pg-text">{shown === "full" ? doc.views.full : doc.views.visible}</pre>
        )}
      </div>
    </div>
  );
}
