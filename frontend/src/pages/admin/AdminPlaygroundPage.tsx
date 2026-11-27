import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, History, Play, RotateCcw, Save, Trash2 } from "@/components/icons";
import Breadcrumb from "@/components/Breadcrumb";
import Drawer from "@/components/Drawer";
import DocPreview from "@/components/playground/DocPreview";
import ResultsGrid from "@/components/playground/ResultsGrid";
import SetupsEditor from "@/components/playground/SetupsEditor";
import { defaultSetup } from "@/components/playground/setups";
import { uploadFile } from "@/api/files";
import {
  apiMessage,
  buildDocument,
  createRun,
  deleteRun,
  deleteSetup,
  fetchCatalog,
  fetchCorpus,
  fetchRun,
  fetchRunDocument,
  listRuns,
  listSetups,
  rerun,
  saveSetup,
  searchFiles,
  type Attack,
  type AttackId,
  type Catalog,
  type CorpusDoc,
  type DocPayload,
  type DocumentResponse,
  type Input,
  type Lang,
  type PickFile,
  type RunDetail,
  type RunSummary,
  type SavedSetup,
  type Setup,
} from "@/api/playground";
import { useToast } from "@/state/toast";
import { formatBytes, formatDateTime } from "@/utils/format";

type InputTab = "text" | "file" | "upload" | "corpus";

const ATTACK_INFO: Record<AttackId, string> = {
  none: "No attack: the document as it is",
  A1: "A1 · class directive (“Classification: PUBLIC…”)",
  A2: "A2 · metadata impersonation (stamp, no command)",
  A3: "A3 · A1/A2 payload in a hidden carrier",
  A4: "A4 · directive in the other language",
  A5: "A5 · padding: public text before the document",
  A6: "A6 · identifier obfuscation",
  A7: "A7 · whole document hidden",
};

const NO_ATTACK: Attack = {
  attack: "none",
  payload_lang: "en",
  placement: "start",
  carrier: "",
  a3_payload: "A1",
  payload: null,
  output_format: "txt",
};

export default function AdminPlaygroundPage() {
  const toast = useToast();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");

  // input
  const [tab, setTab] = useState<InputTab>("corpus");
  const [text, setText] = useState("");
  const [textFormat, setTextFormat] = useState<"txt" | "docx" | "pdf">("docx");
  const [lang, setLang] = useState<Lang>("en");
  const [file, setFile] = useState<PickFile | null>(null);
  const [corpusRef, setCorpusRef] = useState("");
  const [attack, setAttack] = useState<Attack>(NO_ATTACK);

  // preview
  const [doc, setDoc] = useState<DocumentResponse | null>(null);
  const [docBusy, setDocBusy] = useState(false);
  const [docError, setDocError] = useState("");
  const [previewSide, setPreviewSide] = useState<"input" | "attacked">("attacked");

  // setups and run
  const [setups, setSetups] = useState<Setup[]>([]);
  const [explain, setExplain] = useState(false);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [runDocs, setRunDocs] = useState<{ input?: DocPayload; attacked?: DocPayload }>({});
  const [starting, setStarting] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    fetchCatalog()
      .then((c) => {
        setCatalog(c);
        setSetups([
          defaultSetup(c, "nli", "nli_en"),
          ...(c.llm.length
            ? [defaultSetup(c, "llm"), { ...defaultSetup(c, "llm"), defenses: ["D2" as const] }]
            : []),
        ]);
      })
      .catch((e) => setCatalogError(apiMessage(e, "The playground is not available.")));
  }, []);

  const input: Input | null = useMemo(() => {
    if (tab === "text")
      return text.trim() ? { kind: "text", text, text_format: textFormat, lang } : null;
    if (tab === "corpus") return corpusRef ? { kind: "corpus", corpus_ref: corpusRef } : null;
    return file ? { kind: "file", file_id: file.id, lang } : null;
  }, [tab, text, textFormat, lang, file, corpusRef]);

  const buildSeq = useRef(0);
  const refreshDocument = useCallback(async () => {
    if (!input) return;
    const seq = ++buildSeq.current; // only the latest request may update the preview
    setDocBusy(true);
    setDocError("");
    try {
      const built = await buildDocument(input, attack);
      if (seq !== buildSeq.current) return;
      setDoc(built);
      setRun(null);
      setRunDocs({});
    } catch (e) {
      if (seq !== buildSeq.current) return;
      setDoc(null);
      setDocError(apiMessage(e, "Could not build the document."));
    } finally {
      if (seq === buildSeq.current) setDocBusy(false);
    }
  }, [input, attack]);

  // rebuild the preview when a file / corpus document or the attack changes (typed text: on demand)
  const auto = useRef(refreshDocument);
  auto.current = refreshDocument;
  const skipAuto = useRef(false); // set when a stored run is opened: show it, do not rebuild
  useEffect(() => {
    if (skipAuto.current) {
      skipAuto.current = false;
      return;
    }
    if (tab === "text" || !input) return;
    const t = setTimeout(() => void auto.current(), 300);
    return () => clearTimeout(t);
  }, [tab, input, attack]);

  // poll the run until every row is finished; a failed poll retries, a stale answer is dropped
  const [pollRetry, setPollRetry] = useState(0);
  useEffect(() => {
    if (!run || run.status === "done" || run.status === "failed") return;
    let cancelled = false;
    const t = setTimeout(() => {
      fetchRun(run.id)
        .then((r) => {
          if (!cancelled) setRun(r);
        })
        .catch(() => {
          if (!cancelled) setPollRetry((n) => n + 1);
        });
    }, 2000);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [run, pollRetry]);

  async function start() {
    if (!input) return;
    setStarting(true);
    try {
      const r = await createRun({ input, attack, setups, explain });
      setRun(r);
      setRunDocs({});
      toast.success("Run started", `${setups.length} setups; results fill in as they finish.`);
    } catch (e) {
      toast.error("Could not start the run", apiMessage(e, "Unknown error."));
    } finally {
      setStarting(false);
    }
  }

  async function openRun(id: string) {
    setHistoryOpen(false);
    try {
      const [r, inp, att] = await Promise.all([
        fetchRun(id),
        fetchRunDocument(id, "input"),
        fetchRunDocument(id, "attacked"),
      ]);
      skipAuto.current = true;
      setRun(r);
      setRunDocs({ input: inp, attacked: att });
      setSetups(r.rows.map((row) => row.setup));
      setAttack(r.attack);
      setExplain(r.explain);
    } catch (e) {
      toast.error("Could not open the run", apiMessage(e, "Unknown error."));
    }
  }

  if (catalogError) {
    return (
      <div className="page">
        <div className="empty">
          <div className="empty-title">Playground not available</div>
          {catalogError}
        </div>
      </div>
    );
  }
  if (!catalog) return <div className="page text-muted">Loading the playground…</div>;

  const shownDoc =
    (runDocs.input && (previewSide === "input" ? runDocs.input : runDocs.attacked)) ||
    (doc && (previewSide === "input" ? doc.input : doc.attacked));
  const sourceNote =
    runDocs.attacked && previewSide === "attacked"
      ? "stored with the run"
      : doc?.attack_source === "research-variant" && previewSide === "attacked"
        ? "exact file from the research runs"
        : doc?.attack_source === "adapter" && previewSide === "attacked"
          ? "built by the research attack generator"
          : undefined;

  return (
    <div className="page pg-page">
      <Breadcrumb items={[{ label: "Admin", to: "/admin" }, { label: "Classifier playground" }]} />
      <div className="page-header">
        <div className="page-title">
          <h1 className="row row-2">
            <FlaskConical size={22} /> Classifier playground
          </h1>
          <span className="page-subtitle">
            Sandbox mode · one document, any attack, several classifiers side by side. Runs never
            change real files, tiers or access.
          </span>
        </div>
        <div className="page-actions">
          <button type="button" className="btn" onClick={() => setHistoryOpen(true)}>
            <History size={16} /> History
          </button>
        </div>
      </div>

      <ServerStatus catalog={catalog} />

      <div className="pg-grid">
        <div className="stack stack-4">
          <div className="card">
            <div className="card-header">1 · Document</div>
            <div className="card-body stack stack-3">
              <div className="tabs" role="tablist">
                {(
                  [
                    ["corpus", "Research corpus"],
                    ["file", "Stored files"],
                    ["upload", "Upload"],
                    ["text", "Type text"],
                  ] as const
                ).map(([k, label]) => (
                  <button
                    key={k}
                    type="button"
                    role="tab"
                    aria-selected={tab === k}
                    className={`tab ${tab === k ? "active" : ""}`}
                    onClick={() => setTab(k)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {tab === "corpus" && (
                <CorpusPicker enabled={catalog.corpus} value={corpusRef} onChange={setCorpusRef} />
              )}
              {tab === "file" && <FilePicker value={file} onChange={setFile} />}
              {tab === "upload" && (
                <UploadPicker
                  onUploaded={(f) => {
                    setFile(f);
                    setTab("file");
                  }}
                />
              )}
              {tab === "text" && (
                <div className="stack stack-2">
                  <textarea
                    className="textarea"
                    rows={8}
                    placeholder="Paste or type a document…"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                  <div className="row row-3">
                    <label className="row row-2 text-small">
                      Render as
                      <select
                        className="select"
                        value={textFormat}
                        onChange={(e) => setTextFormat(e.target.value as "txt" | "docx" | "pdf")}
                      >
                        <option value="docx">DOCX</option>
                        <option value="pdf">PDF</option>
                        <option value="txt">TXT</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={!input || docBusy}
                      onClick={() => void refreshDocument()}
                    >
                      Show document
                    </button>
                  </div>
                </div>
              )}
              {(tab === "text" || tab === "file") && (
                <label className="row row-2 text-small">
                  Document language
                  <select
                    className="select"
                    value={lang}
                    onChange={(e) => setLang(e.target.value as Lang)}
                  >
                    <option value="en">English</option>
                    <option value="uk">Ukrainian</option>
                  </select>
                </label>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">2 · Attack</div>
            <div className="card-body">
              <AttackPanel catalog={catalog} attack={attack} onChange={setAttack} />
            </div>
          </div>
        </div>

        <div className="card pg-preview-card">
          <div className="card-header row row-between">
            <span>Preview</span>
            <div className="preview-tabs" role="tablist" aria-label="Input or attacked">
              {(["input", "attacked"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  role="tab"
                  aria-selected={previewSide === s}
                  className="btn btn-sm btn-ghost"
                  onClick={() => setPreviewSide(s)}
                >
                  {s === "input" ? "Original" : "Attacked"}
                </button>
              ))}
            </div>
          </div>
          <div className="card-body">
            {docBusy && <p className="text-muted">Building the document…</p>}
            {docError && <p className="field-error">{docError}</p>}
            {!docBusy && !docError && shownDoc && (
              <DocPreview
                key={`${shownDoc.filename}:${shownDoc.data_b64.length}`}
                doc={shownDoc}
                note={sourceNote}
              />
            )}
            {!docBusy && !docError && !shownDoc && (
              <div className="empty">
                <div className="empty-title">No document yet</div>
                Pick a corpus document or a stored file, or type text.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: "var(--space-4)" }}>
        <div className="card-header row row-between">
          <span>3 · Classifier setups</span>
          <SavedSetups setups={setups} onLoad={setSetups} />
        </div>
        <div className="card-body stack stack-3">
          <SetupsEditor catalog={catalog} setups={setups} onChange={setSetups} />
          <div className="row row-between" style={{ flexWrap: "wrap", gap: "var(--space-3)" }}>
            <div className="row row-2">
              <button
                type="button"
                className="btn btn-sm"
                disabled={setups.length >= 12}
                onClick={() => setSetups([...setups, defaultSetup(catalog, "nli")])}
              >
                + NLI setup
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={setups.length >= 12 || !catalog.llm.length}
                onClick={() => setSetups([...setups, defaultSetup(catalog, "llm")])}
              >
                + LLM setup
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                title="Back to the research settings"
                onClick={() =>
                  setSetups(
                    setups.map((s) => ({
                      ...defaultSetup(catalog, s.engine, s.model),
                      defenses: s.defenses,
                      label: s.label,
                      expected_tier: s.expected_tier,
                    })),
                  )
                }
              >
                <RotateCcw size={14} /> Research defaults
              </button>
            </div>
            <div className="row row-3">
              <label
                className="pg-chip"
                title="LLM rows: one more call that asks the model for a one-sentence reason"
              >
                <input
                  type="checkbox"
                  checked={explain}
                  onChange={(e) => setExplain(e.target.checked)}
                />
                Ask LLMs to explain
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!input || !setups.length || starting}
                onClick={() => void start()}
              >
                <Play size={16} /> {starting ? "Starting…" : "Run"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {run && (
        <div className="card" style={{ marginTop: "var(--space-4)" }}>
          <div className="card-header row row-between">
            <span>
              4 · Results <span className="text-muted text-small">· {run.title}</span>
            </span>
            <span className="text-small text-muted">
              {run.status === "done" || run.status === "failed"
                ? `finished · ${formatDateTime(run.created_at)}`
                : `${run.rows.filter((r) => r.status === "done" || r.status === "failed").length} of ${run.rows.length} done…`}
            </span>
          </div>
          <div className="card-body">
            <ResultsGrid rows={run.rows} />
          </div>
        </div>
      )}

      <Drawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title="Run history"
        subtitle="Every run with its documents, setups and results."
      >
        {historyOpen && (
          <HistoryList
            onOpen={(id) => void openRun(id)}
            onRerun={(r) => {
              setRun(r);
              setRunDocs({});
              setHistoryOpen(false);
            }}
          />
        )}
      </Drawer>
    </div>
  );
}

function ServerStatus({ catalog }: { catalog: Catalog }) {
  const problems = [
    !catalog.nli_server && "NLI server (host GPU) is not running",
    catalog.llm_error,
  ].filter(Boolean);
  if (!problems.length) return null;
  return (
    <p className="pg-warning">
      {problems.join(" · ")}. Start everything with{" "}
      <span className="text-mono">make playground</span>; rows that need a missing server will fail,
      the others still run.
    </p>
  );
}

function CorpusPicker({
  enabled,
  value,
  onChange,
}: {
  enabled: boolean;
  value: string;
  onChange: (ref: string) => void;
}) {
  const [docs, setDocs] = useState<CorpusDoc[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => {
    if (enabled)
      fetchCorpus()
        .then(setDocs)
        .catch(() => setDocs([]));
  }, [enabled]);
  if (!enabled) return <p className="text-muted">The research corpus is not on this machine.</p>;
  const shown = docs.filter(
    (d) => !q || `${d.pair_id} ${d.tier} ${d.lang}`.includes(q.toLowerCase()),
  );
  return (
    <div className="stack stack-2">
      <input
        className="input"
        placeholder="Filter: id, tier or language (e.g. restricted uk)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="pg-list" role="listbox" aria-label="Corpus documents">
        {shown.map((d) => (
          <button
            key={d.ref}
            type="button"
            role="option"
            aria-selected={value === d.ref}
            className="pg-list-item"
            onClick={() => onChange(d.ref)}
          >
            <span className="text-mono">{d.pair_id}</span>
            <span className="text-small text-muted">
              {d.lang.toUpperCase()} · {d.words} words{d.difficulty === "hard" ? " · hard" : ""}
            </span>
            <span className={`badge badge-${d.tier}`}>{d.tier}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function FilePicker({
  value,
  onChange,
}: {
  value: PickFile | null;
  onChange: (f: PickFile) => void;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<PickFile[]>([]);
  useEffect(() => {
    const t = setTimeout(() => {
      searchFiles(q)
        .then(setItems)
        .catch(() => setItems([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="stack stack-2">
      <input
        className="input"
        placeholder="Search any user's PDF, DOCX or TXT by name"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="pg-list" role="listbox" aria-label="Stored files">
        {items.map((f) => (
          <button
            key={f.id}
            type="button"
            role="option"
            aria-selected={value?.id === f.id}
            className="pg-list-item"
            onClick={() => onChange(f)}
          >
            <span className="text-mono">{f.filename}</span>
            <span className="text-small text-muted">
              {f.owner} · {formatBytes(f.size_bytes)}
            </span>
          </button>
        ))}
        {!items.length && <p className="text-small text-muted">No matching files.</p>}
      </div>
      <p className="text-small text-muted" style={{ margin: 0 }}>
        Using a file is logged in the audit trail. The run keeps its own encrypted copy.
      </p>
    </div>
  );
}

function UploadPicker({ onUploaded }: { onUploaded: (f: PickFile) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function onPick(f: File | undefined) {
    if (!f) return;
    setBusy(true);
    try {
      const stored = await uploadFile(f);
      onUploaded({
        id: stored.id,
        filename: stored.original_filename,
        owner: "you",
        size_bytes: stored.size_bytes,
        uploaded_at: stored.uploaded_at,
      });
      toast.success("Uploaded", `${f.name} is stored and classified like any other upload.`);
    } catch (e) {
      toast.error("Upload failed", apiMessage(e, "Unknown error."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack stack-2">
      <input
        type="file"
        className="input"
        accept=".pdf,.docx,.txt,.md"
        disabled={busy}
        onChange={(e) => void onPick(e.target.files?.[0])}
      />
      <p className="text-small text-muted" style={{ margin: 0 }}>
        The file goes through the normal upload (encrypted, classified, in your files), then opens
        here.
      </p>
    </div>
  );
}

function AttackPanel({
  catalog,
  attack,
  onChange,
}: {
  catalog: Catalog;
  attack: Attack;
  onChange: (a: Attack) => void;
}) {
  const a = catalog.attacks;
  const set = (p: Partial<Attack>) => onChange({ ...attack, ...p });
  const id = attack.attack;
  const carriers =
    id === "A3"
      ? [...a.docx_carriers.map((c) => `docx:${c}`), ...a.pdf_carriers.map((c) => `pdf:${c}`)]
      : id === "A7"
        ? [
            ...a.a7_carriers.docx.map((c) => `docx:${c}`),
            ...a.a7_carriers.pdf.map((c) => `pdf:${c}`),
          ]
        : id === "A6"
          ? a.obfuscations
          : [];
  const payloadKind = id === "A3" ? attack.a3_payload : id === "A4" ? "A1" : id;
  const defaultPayload = a.payloads[payloadKind]?.[attack.payload_lang] ?? "";
  const hasPayload = ["A1", "A2", "A3", "A4"].includes(id);

  return (
    <div className="stack stack-3">
      <select
        className="select"
        value={id}
        onChange={(e) => {
          const next = e.target.value as AttackId;
          const first =
            next === "A3" ? "vanish" : next === "A7" ? "vanish" : next === "A6" ? "zero_width" : "";
          onChange({ ...attack, attack: next, carrier: first, payload: null });
        }}
      >
        {a.attacks.map((x) => (
          <option key={x} value={x}>
            {ATTACK_INFO[x]}
          </option>
        ))}
      </select>
      {id !== "none" && (
        <div className="pg-settings">
          {carriers.length > 0 && (
            <label className="field">
              <span className="field-label">{id === "A6" ? "Obfuscation" : "Carrier"}</span>
              <select
                className="select"
                value={
                  id === "A6"
                    ? attack.carrier
                    : (carriers.find((c) => c.endsWith(`:${attack.carrier}`)) ?? carriers[0])
                }
                onChange={(e) => set({ carrier: e.target.value.split(":").pop() ?? "" })}
              >
                {carriers.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(":", " · ")}
                  </option>
                ))}
              </select>
            </label>
          )}
          {id === "A3" && (
            <label className="field">
              <span className="field-label">Hidden payload</span>
              <select
                className="select"
                value={attack.a3_payload}
                onChange={(e) => set({ a3_payload: e.target.value as "A1" | "A2", payload: null })}
              >
                <option value="A1">A1 · class directive</option>
                <option value="A2">A2 · metadata stamp</option>
              </select>
            </label>
          )}
          {["A1", "A2", "A4"].includes(id) && (
            <label className="field">
              <span className="field-label">Placement</span>
              <select
                className="select"
                value={attack.placement}
                onChange={(e) => set({ placement: e.target.value as "start" | "end" })}
              >
                <option value="start">Start (after the title)</option>
                <option value="end">End</option>
              </select>
            </label>
          )}
          {hasPayload && (
            <label className="field">
              <span className="field-label">Payload language</span>
              <select
                className="select"
                value={attack.payload_lang}
                onChange={(e) => set({ payload_lang: e.target.value as Lang, payload: null })}
              >
                <option value="en">English</option>
                <option value="uk">Ukrainian</option>
              </select>
            </label>
          )}
          {["A1", "A2", "A4", "A5", "A6"].includes(id) && (
            <label className="field">
              <span className="field-label">Output format</span>
              <select
                className="select"
                value={attack.output_format}
                onChange={(e) => set({ output_format: e.target.value as "txt" | "docx" | "pdf" })}
              >
                <option value="txt">TXT (as in the research)</option>
                <option value="docx">DOCX</option>
                <option value="pdf">PDF</option>
              </select>
            </label>
          )}
          {hasPayload && (
            <label className="field" style={{ gridColumn: "1 / -1" }}>
              <span className="field-label">
                Payload {attack.payload !== null ? "(edited — no research file matches)" : ""}
              </span>
              <textarea
                className="textarea"
                rows={2}
                value={attack.payload ?? defaultPayload}
                onChange={(e) =>
                  set({ payload: e.target.value === defaultPayload ? null : e.target.value })
                }
              />
            </label>
          )}
        </div>
      )}
    </div>
  );
}

function SavedSetups({ setups, onLoad }: { setups: Setup[]; onLoad: (s: Setup[]) => void }) {
  const toast = useToast();
  const [items, setItems] = useState<SavedSetup[]>([]);
  const reload = () =>
    listSetups()
      .then(setItems)
      .catch(() => setItems([]));
  useEffect(() => {
    void reload();
  }, []);
  async function onSave() {
    const name = window.prompt("Name for this set of setups");
    if (!name) return;
    try {
      await saveSetup(name, setups);
      toast.success("Saved", name);
      void reload();
    } catch (e) {
      toast.error("Could not save", apiMessage(e, "Unknown error."));
    }
  }
  return (
    <div className="row row-2">
      <select
        className="select btn-sm"
        style={{ width: "auto", height: 28 }}
        value=""
        aria-label="Load saved setups"
        onChange={(e) => {
          const s = items.find((x) => x.id === e.target.value);
          if (s) onLoad(s.rows);
        }}
      >
        <option value="">Load saved…</option>
        {items.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.rows.length})
          </option>
        ))}
      </select>
      <button type="button" className="btn btn-sm btn-ghost" onClick={() => void onSave()}>
        <Save size={14} /> Save as…
      </button>
      {items.length > 0 && (
        <select
          className="select btn-sm"
          style={{ width: "auto", height: 28 }}
          value=""
          aria-label="Delete a saved setup"
          onChange={async (e) => {
            const s = items.find((x) => x.id === e.target.value);
            if (s && window.confirm(`Delete saved setups “${s.name}”?`)) {
              try {
                await deleteSetup(s.id);
              } catch (err) {
                toast.error("Could not delete", apiMessage(err, "Unknown error."));
              }
              void reload();
            }
          }}
        >
          <option value="">Delete…</option>
          {items.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function HistoryList({
  onOpen,
  onRerun,
}: {
  onOpen: (id: string) => void;
  onRerun: (r: RunDetail) => void;
}) {
  const toast = useToast();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const reload = () =>
    listRuns()
      .then(setRuns)
      .catch(() => setRuns([]));
  useEffect(() => {
    void reload();
  }, []);
  if (runs === null) return <p className="text-muted">Loading…</p>;
  if (!runs.length) return <div className="empty">No runs yet.</div>;
  return (
    <div className="stack stack-2">
      {runs.map((r) => (
        <div key={r.id} className="pg-history-item">
          <button type="button" className="pg-history-open" onClick={() => onOpen(r.id)}>
            <span className="text-strong">{r.title}</span>
            <span className="text-small text-muted">
              {formatDateTime(r.created_at)} · {r.rows} setups · {r.status}
              {r.attack_source === "research-variant" ? " · research file" : ""}
            </span>
          </button>
          <div className="row row-2">
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={async () => {
                try {
                  onRerun(await rerun(r.id));
                } catch (e) {
                  toast.error("Could not rerun", apiMessage(e, "Unknown error."));
                }
              }}
            >
              <RotateCcw size={14} /> Rerun
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost btn-icon"
              aria-label={`Delete run ${r.title}`}
              onClick={async () => {
                if (!window.confirm("Delete this run and its stored documents?")) return;
                try {
                  await deleteRun(r.id);
                } catch (e) {
                  toast.error("Could not delete the run", apiMessage(e, "Unknown error."));
                }
                void reload();
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
