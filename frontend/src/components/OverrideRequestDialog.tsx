import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { createOverrideRequest, Tier } from "@/api/tierOverrides";

const TIERS: Tier[] = ["public", "internal", "confidential", "restricted"];

interface Props {
  fileId: string;
  fileLabel: string;
  currentTier: Tier | null;
  onClose: () => void;
  onSubmitted: () => void;
}

export default function OverrideRequestDialog({
  fileId,
  fileLabel,
  currentTier,
  onClose,
  onSubmitted,
}: Props) {
  const [requestedTier, setRequestedTier] = useState<Tier>(
    currentTier === "public" ? "internal" : "public",
  );
  const [justification, setJustification] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await createOverrideRequest(fileId, requestedTier, justification);
      onSubmitted();
      onClose();
    } catch (err) {
      const ax = err as AxiosError<{ error?: string; message?: string }>;
      setError(ax.response?.data?.message ?? "Could not submit request.");
    } finally {
      setBusy(false);
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
          minWidth: "28rem",
          maxWidth: "36rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>
          Request tier change for <code>{fileLabel}</code>
        </h3>
        <p style={{ color: "#6e7781" }}>
          Current tier:{" "}
          <strong>{currentTier ?? "not classified yet"}</strong>. An admin
          must approve before the file's tier changes.
        </p>
        <form onSubmit={onSubmit}>
          <p>
            <label>
              Requested tier
              <br />
              <select
                value={requestedTier}
                onChange={(e) => setRequestedTier(e.target.value as Tier)}
                style={{ width: "100%", padding: "0.5rem" }}
              >
                {TIERS.map((t) => (
                  <option key={t} value={t} disabled={t === currentTier}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </p>
          <p>
            <label>
              Justification (required)
              <br />
              <textarea
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                required
                rows={4}
                style={{ width: "100%", padding: "0.5rem" }}
                placeholder="Why should the tier change?"
              />
            </label>
          </p>
          {error && <p className="status-fail">{error}</p>}
          <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" disabled={busy || !justification.trim()}>
              {busy ? "Submitting…" : "Request review"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
