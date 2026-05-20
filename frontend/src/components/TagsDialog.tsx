import { FormEvent, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { addTags, listTags, removeTag, Tag } from "@/api/tags";

interface Props {
  fileId: string;
  fileLabel: string;
  onClose: () => void;
}

export default function TagsDialog({ fileId, fileLabel, onClose }: Props) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const items = await listTags(fileId);
      setTags(items);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Could not load tags.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId]);

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setError(null);
    setBusy(true);
    try {
      // Allow comma-separated input: "q3, draft" → two tags
      const names = input
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const updated = await addTags(fileId, names);
      setTags(updated);
      setInput("");
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Could not add tag.");
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(tag: Tag) {
    setError(null);
    try {
      await removeTag(fileId, tag.id);
      setTags((prev) => prev.filter((t) => t.id !== tag.id));
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Could not remove tag.");
    }
  }

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
          minWidth: "26rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>
          Tags on <code>{fileLabel}</code>
        </h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "1rem" }}>
          {tags.length === 0 && (
            <span style={{ color: "#6e7781" }}>No tags yet.</span>
          )}
          {tags.map((t) => (
            <span
              key={t.id}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                padding: "0.1rem 0.5rem",
                background: "#eaeef2",
                border: "1px solid #d0d7de",
                borderRadius: "12px",
                fontSize: "0.85em",
              }}
            >
              #{t.name}
              <button
                type="button"
                onClick={() => onRemove(t)}
                title="Remove"
                style={{
                  border: "none",
                  background: "transparent",
                  padding: 0,
                  cursor: "pointer",
                  color: "#6e7781",
                  fontWeight: "bold",
                }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <form onSubmit={onAdd}>
          <p>
            <label>
              New tag(s) — comma-separated
              <br />
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="q3, draft"
                autoFocus
                style={{ width: "100%", padding: "0.5rem" }}
              />
            </label>
          </p>
          {error && <p className="status-fail">{error}</p>}
          <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose}>
              Close
            </button>
            <button type="submit" disabled={busy || !input.trim()}>
              {busy ? "Adding…" : "Add"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
