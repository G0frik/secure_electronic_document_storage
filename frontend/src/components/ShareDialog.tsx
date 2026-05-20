import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { createShare, ShareTargetType } from "@/api/shares";
import { createShareLink, ShareLink } from "@/api/shareLinks";

interface Props {
  targetType: ShareTargetType;
  targetId: string;
  targetLabel: string;
  onClose: () => void;
  onShared: () => void;
}

type Mode = "internal" | "external";

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
          maxWidth: "32rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>
          Share {targetType}: <code>{targetLabel}</code>
        </h3>

        {targetType === "file" && (
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button
              type="button"
              onClick={() => setMode("internal")}
              disabled={mode === "internal"}
            >
              Internal user
            </button>
            <button
              type="button"
              onClick={() => setMode("external")}
              disabled={mode === "external"}
            >
              External link
            </button>
          </div>
        )}

        {mode === "internal" && (
          <form onSubmit={onSubmitInternal}>
            <p>
              <label>
                Recipient email
                <br />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  style={{ width: "100%", padding: "0.5rem" }}
                />
              </label>
            </p>
            <p>
              <label>
                Permission
                <br />
                <select
                  value={permission}
                  onChange={(e) => setPermission(e.target.value as "viewer" | "editor")}
                  style={{ width: "100%", padding: "0.5rem" }}
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                </select>
              </label>
            </p>
            {error && <p className="status-fail">{error}</p>}
            <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" disabled={busy || !email}>
                {busy ? "Sharing…" : "Share"}
              </button>
            </p>
          </form>
        )}

        {mode === "external" && !minted && (
          <form onSubmit={onSubmitExternal}>
            <p style={{ color: "#6e7781" }}>
              Anyone with the link can download until it expires or hits the use limit.
              The link is shown <strong>once</strong> — copy it now.
            </p>
            <p>
              <label>
                Expires (optional)
                <br />
                <input
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(e) => setExpiresAt(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem" }}
                />
              </label>
            </p>
            <p>
              <label>
                Max uses (optional)
                <br />
                <input
                  type="number"
                  min={1}
                  value={maxUses}
                  onChange={(e) => setMaxUses(e.target.value)}
                  placeholder="unlimited"
                  style={{ width: "100%", padding: "0.5rem" }}
                />
              </label>
            </p>
            <p>
              <label>
                <input
                  type="checkbox"
                  checked={forceRestricted}
                  onChange={(e) => setForceRestricted(e.target.checked)}
                />{" "}
                Force link for RESTRICTED tier (admin override)
              </label>
            </p>
            {error && <p className="status-fail">{error}</p>}
            <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create link"}
              </button>
            </p>
          </form>
        )}

        {mode === "external" && minted && minted.token && (
          <div>
            <p>Link created. Copy it — you won't see it again.</p>
            <input
              type="text"
              value={publicUrl(minted.token)}
              readOnly
              onFocus={(e) => e.target.select()}
              style={{
                width: "100%",
                padding: "0.5rem",
                fontFamily: "Consolas, monospace",
                background: "#f6f8fa",
              }}
            />
            <p style={{ color: "#6e7781", fontSize: "0.9em" }}>
              {minted.max_uses !== null && `${minted.max_uses} uses max · `}
              {minted.expires_at
                ? `expires ${new Date(minted.expires_at).toLocaleString()}`
                : "no expiry set"}
            </p>
            <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => navigator.clipboard?.writeText(publicUrl(minted.token!))}
              >
                Copy
              </button>
              <button type="button" onClick={onClose}>
                Done
              </button>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
