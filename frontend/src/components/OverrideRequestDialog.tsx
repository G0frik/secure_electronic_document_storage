import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { createOverrideRequest, Tier } from "@/api/tierOverrides";
import Drawer from "@/components/Drawer";

const TIERS: Tier[] = ["public", "internal", "confidential", "restricted"];

interface Props {
  fileId: string;
  fileLabel: string;
  currentTier: Tier | null;
  onClose: () => void;
  onSubmitted: () => void;
}

/**
 * Tier-override request drawer.
 *
 * Owner files a request for an admin to re-tier the file. Justification
 * is required (server-enforced). The current tier is displayed but the
 * dropdown disables it so the user can't request the same tier.
 */
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
    <Drawer
      open
      onClose={onClose}
      title="Request tier change"
      subtitle={<span className="filename">{fileLabel}</span>}
    >
      <p className="text-small text-muted">
        Current tier: <strong>{currentTier ?? "not classified yet"}</strong>. An admin must approve
        before the file's tier changes.
      </p>

      <form onSubmit={onSubmit} className="stack stack-4">
        <div className="field">
          <label className="field-label" htmlFor="override-tier">
            Requested tier
          </label>
          <select
            id="override-tier"
            className="select"
            value={requestedTier}
            onChange={(e) => setRequestedTier(e.target.value as Tier)}
          >
            {TIERS.map((t) => (
              <option key={t} value={t} disabled={t === currentTier}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="override-justification">
            Justification
          </label>
          <textarea
            id="override-justification"
            className="textarea"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            required
            rows={5}
            placeholder="Why should the tier change?"
          />
          <span className="field-hint">Be specific — the admin reviewing this needs context.</span>
        </div>
        {error && <p className="field-error">{error}</p>}
        <div className="row row-2" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !justification.trim()}
          >
            {busy ? "Submitting…" : "Request review"}
          </button>
        </div>
      </form>
    </Drawer>
  );
}
