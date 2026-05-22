import { FormEvent, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { addTags, listTags, removeTag, Tag } from "@/api/tags";
import Drawer from "@/components/Drawer";
import { Close } from "@/components/icons";

interface Props {
  fileId: string;
  fileLabel: string;
  onClose: () => void;
}

/**
 * Tags drawer — manage a file's tags inline.
 *
 * Comma-separated input creates multiple tags at once. Tags display as
 * removable chips. Internal logic is unchanged from the pre-redesign
 * version; only the outer wrapper became a Drawer.
 */
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
    <Drawer
      open
      onClose={onClose}
      title="Tags"
      subtitle={<span className="filename">{fileLabel}</span>}
      footer={
        <button type="button" className="btn" onClick={onClose}>
          Done
        </button>
      }
    >
      <div className="row row-2" style={{ flexWrap: "wrap" }}>
        {tags.length === 0 && <span className="text-small text-muted">No tags yet.</span>}
        {tags.map((t) => (
          <span
            key={t.id}
            className="row row-2"
            style={{
              padding: "2px var(--space-2)",
              background: "var(--color-accent-soft)",
              color: "var(--color-accent)",
              borderRadius: "var(--radius-pill)",
              fontSize: "0.8125rem",
              fontFamily: "var(--font-mono)",
            }}
          >
            #{t.name}
            <button
              type="button"
              onClick={() => onRemove(t)}
              aria-label={`Remove tag ${t.name}`}
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                color: "var(--color-accent)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
              }}
            >
              <Close size={12} />
            </button>
          </span>
        ))}
      </div>

      <form onSubmit={onAdd} className="stack stack-3">
        <div className="field">
          <label className="field-label" htmlFor="tag-input">
            Add tags
          </label>
          <input
            id="tag-input"
            className="input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="q3, draft, hr"
            autoFocus
          />
          <span className="field-hint">Separate multiple tags with commas.</span>
        </div>
        {error && <p className="field-error">{error}</p>}
        <div>
          <button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </div>
      </form>
    </Drawer>
  );
}
