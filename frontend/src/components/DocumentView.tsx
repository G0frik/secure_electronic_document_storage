import { useEffect, useRef, useState } from "react";
import { fetchPreviewDocument } from "@/api/files";

interface Props {
  fileId: string;
  kind: "pdf" | "docx";
}

// Rendering every page of a huge PDF would freeze the tab; the rest is one click away (download).
const MAX_PDF_PAGES = 50;
const SAFE_HREF = /^(https?:|mailto:|#)/i;

async function renderPdf(data: ArrayBuffer, host: HTMLElement): Promise<number> {
  const pdfjs = await import("pdfjs-dist");
  const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  // pdf.js core never runs PDF JavaScript (that needs the viewer's scripting); no XFA → no HTML forms
  const doc = await pdfjs.getDocument({ data, enableXfa: false }).promise;
  const pages = Math.min(doc.numPages, MAX_PDF_PAGES);
  for (let n = 1; n <= pages; n++) {
    const page = await doc.getPage(n);
    const viewport = page.getViewport({ scale: 1.4 });
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.className = "document-page";
    canvas.setAttribute("aria-label", `Page ${n}`);
    host.appendChild(canvas);
    await page.render({ canvas, viewport }).promise;
  }
  return doc.numPages;
}

async function renderDocx(data: ArrayBuffer, host: HTMLElement): Promise<void> {
  const { renderAsync } = await import("docx-preview");
  await renderAsync(data, host, undefined, {
    inWrapper: true,
    ignoreLastRenderedPageBreak: true,
    useBase64URL: true, // images as data: URLs, no object URLs left behind
  });
  // A DOCX can carry javascript: or file: links; keep only web, mail and in-page ones.
  host.querySelectorAll("a[href]").forEach((a) => {
    const href = a.getAttribute("href") ?? "";
    if (!SAFE_HREF.test(href)) {
      a.removeAttribute("href");
    } else if (!href.startsWith("#")) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    }
  });
}

/** The file rendered the way a reader sees it (pages, tables, fonts), not as extracted text. */
export default function DocumentView({ fileId, kind }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [note, setNote] = useState("");

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    el.replaceChildren();
    setStatus("loading");
    setNote("");
    fetchPreviewDocument(fileId)
      .then(async (data) => {
        if (cancelled) return;
        if (kind === "pdf") {
          const total = await renderPdf(data, el);
          if (total > MAX_PDF_PAGES) {
            setNote(`Showing the first ${MAX_PDF_PAGES} of ${total} pages. Download to see all.`);
          }
        } else {
          await renderDocx(data, el);
        }
        if (!cancelled) setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatus("error");
        setNote(err instanceof Error ? err.message : "Could not render the document.");
      });
    return () => {
      cancelled = true;
      el.replaceChildren();
    };
  }, [fileId, kind]);

  return (
    <div>
      {status === "loading" && <p className="text-muted">Rendering document…</p>}
      {note && <p className={status === "error" ? "field-error" : "text-small text-muted"}>{note}</p>}
      <div ref={host} className="document-view" />
    </div>
  );
}
