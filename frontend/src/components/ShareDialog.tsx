import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { createShare, ShareTargetType } from "@/api/shares";

interface Props {
  targetType: ShareTargetType;
  targetId: string;
  targetLabel: string;
  onClose: () => void;
  onShared: () => void;
}

export default function ShareDialog({
  targetType,
  targetId,
  targetLabel,
  onClose,
  onShared,
}: Props) {
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<"viewer" | "editor">("viewer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
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
      const ax = err as AxiosError<{ error?: string; message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to create share.");
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
          minWidth: "24rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>
          Share {targetType}: <code>{targetLabel}</code>
        </h3>
        <form onSubmit={onSubmit}>
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
      </div>
    </div>
  );
}
