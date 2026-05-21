import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { createShare, ShareTargetType } from "@/api/shares";
import { createShareLink, ShareLink } from "@/api/shareLinks";
import Drawer from "@/components/Drawer";

interface Props {
  targetType: ShareTargetType;
  targetId: string;
  targetLabel: string;
  onClose: () => void;
  onShared: () => void;
}

type Mode = "internal" | "external";

/**
 * Share drawer.
 *
 * Two flows side-by-side: internal share (recipient email + viewer/editor
 * permission) and external link (expires + max uses + RESTRICTED override).
 * External links show their raw token exactly once.
 *
 * Folders only support internal sharing — the mode tabs hide for folders.
 */
export default function ShareDialog({
  targetType,
  targetId,
  targetLabel,
  onClose,
  onShared,
}: Props) {
  const [mode, setMode] = useState<Mode>("internal");
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<"viewer" | "editor">("viewer");

  const [expiresAt, setExpiresAt] = useState<string>("");
  const [maxUses, setMaxUses] = useState<string>("");
  const [forceRestricted, setForceRestricted] = useState(false);
  const [minted, setMinted] = useState<ShareLink | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmitInternal(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await createShare({
        target_type: targetType,
        target_id: targetId,
        recipient_email: email,
        permission,
      });
      onShared();
      onClose();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to create share.");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitExternal(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await createShareLink({
        file_id: targetId,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        max_uses: maxUses ? Number(maxUses) : null,
        force_for_restricted: forceRestricted,
      });
      setMinted(created);
      onShared();
    } catch (err) {
      const ax = err as AxiosError<{ error?: string; message?: string }>;
      if (ax.response?.data?.error === "tier_blocked") {
        setError(
          (ax.response?.data?.message ?? "Tier blocked.") +
            " Admins can override with the checkbox below.",
        );
      } else {
        setError(ax.response?.data?.message ?? "Failed to create link.");
      }
    } finally {
      setBusy(false);
    }
  }

  function publicUrl(token: string): string {
    return `${window.location.origin}/share/${token}`;
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title={`Share ${targetType}`}
      subtitle={<span className="filename">{targetLabel}</span>}
    >
      {targetType === "file" && (
        <div className="tabs" style={{ marginBottom: 0 }}>
          <button
            type="button"
            className={mode === "internal" ? "tab active" : "tab"}
            onClick={() => setMode("internal")}
          >
            Internal user
          </button>
          <button
            type="button"
            className={mode === "external" ? "tab active" : "tab"}
            onClick={() => setMode("external")}
          >
            External link
          </button>
        </div>
      )}

      {mode === "internal" && (
        <form onSubmit={onSubmitInternal} className="stack stack-4">
          <div className="field">
            <label className="field-label" htmlFor="share-email">
              Recipient email
            </label>
            <input
              id="share-email"
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="share-permission">
              Permission
            </label>
            <select
              id="share-permission"
              className="select"
              value={permission}
              onChange={(e) =>
                setPermission(e.target.value as "viewer" | "editor")
              }
            >
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
            </select>
            <span className="field-hint">
              Viewer can read; editor is reserved for future upload-into-shared
              behaviour.
            </span>
          </div>
          {error && <p className="field-error">{error}</p>}
          <div className="row row-2" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !email}
            >
              {busy ? "Sharing…" : "Share"}
            </button>
          </div>
        </form>
      )}

      {mode === "external" && !minted && (
        <form onSubmit={onSubmitExternal} className="stack stack-4">
          <p className="text-small text-muted">
            Anyone with the link can download until it expires or hits the use
            limit. The link is shown <strong>once</strong> — copy it now.
          </p>
          <div className="field">
            <label className="field-label" htmlFor="share-expires">
              Expires
            </label>
            <input
              id="share-expires"
              className="input"
              type="datetime-local"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
            <span className="field-hint">Optional. Leave blank for no expiry.</span>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="share-max-uses">
              Maximum downloads
            </label>
            <input
              id="share-max-uses"
              className="input"
              type="number"
              min={1}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              placeholder="unlimited"
            />
          </div>
          <label
            className="row row-2 text-small"
            style={{ cursor: "pointer" }}
          >
            <input
              type="checkbox"
              checked={forceRestricted}
              onChange={(e) => setForceRestricted(e.target.checked)}
            />
            <span>
              Force link for RESTRICTED tier
              <span className="text-muted"> (admin override)</span>
            </span>
          </label>
          {error && <p className="field-error">{error}</p>}
          <div className="row row-2" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Creating…" : "Create link"}
            </button>
          </div>
        </form>
      )}

      {mode === "external" && minted && minted.token && (
        <div className="stack stack-4">
          <p className="text-small">
            Link created. Copy it now — you won't see it again.
          </p>
          <input
            type="text"
            className="input text-mono text-small"
            value={publicUrl(minted.token)}
            readOnly
            onFocus={(e) => e.target.select()}
          />
          <p className="text-small text-muted">
            {minted.max_uses !== null && `${minted.max_uses} downloads max · `}
            {minted.expires_at
              ? `expires ${new Date(minted.expires_at).toLocaleString()}`
              : "no expiry set"}
          </p>
          <div className="row row-2" style={{ justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn"
              onClick={() =>
                navigator.clipboard?.writeText(publicUrl(minted.token!))
              }
            >
              Copy link
            </button>
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      )}
    </Drawer>
  );
}
