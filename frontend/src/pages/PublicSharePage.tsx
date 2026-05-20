import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchPublicShareLink,
  PublicShareLinkInfo,
  publicShareDownloadUrl,
} from "@/api/shareLinks";
import { formatBytes, formatDateTime } from "@/utils/format";

type State =
  | { kind: "loading" }
  | { kind: "ok"; info: PublicShareLinkInfo }
  | { kind: "missing" }
  | { kind: "expired" }
  | { kind: "revoked" }
  | { kind: "exhausted" };

export default function PublicSharePage() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (!token) {
      setState({ kind: "missing" });
      return;
    }
    fetchPublicShareLink(token).then(({ info, invalid }) => {
      if (info) {
        setState({ kind: "ok", info });
      } else if (invalid?.reason === "expired") {
        setState({ kind: "expired" });
      } else if (invalid?.reason === "revoked") {
        setState({ kind: "revoked" });
      } else if (invalid?.reason === "exhausted") {
        setState({ kind: "exhausted" });
      } else {
        setState({ kind: "missing" });
      }
    });
  }, [token]);

  return (
    <main>
      <h1>Secure Document Storage</h1>
      <p style={{ color: "#6e7781" }}>External share link</p>

      {state.kind === "loading" && <p className="status-pending">Loading…</p>}

      {state.kind === "missing" && (
        <p className="status-fail">
          This link does not exist or has been removed.
        </p>
      )}
      {state.kind === "expired" && (
        <p className="status-fail">This link has expired.</p>
      )}
      {state.kind === "revoked" && (
        <p className="status-fail">This link was revoked by the sender.</p>
      )}
      {state.kind === "exhausted" && (
        <p className="status-fail">This link has reached its download limit.</p>
      )}

      {state.kind === "ok" && (
        <div style={{ border: "1px solid #d0d7de", padding: "1.25rem", marginTop: "1rem" }}>
          <p style={{ marginTop: 0 }}>
            <strong>{state.info.filename}</strong>
          </p>
          <p style={{ color: "#6e7781" }}>
            {formatBytes(state.info.size_bytes)} · <code>{state.info.mime_type}</code>
          </p>
          <p style={{ color: "#6e7781", fontSize: "0.9em" }}>
            {state.info.max_uses !== null && (
              <>
                {state.info.remaining_uses}/{state.info.max_uses} downloads remaining
                {state.info.expires_at && " · "}
              </>
            )}
            {state.info.expires_at && (
              <>expires {formatDateTime(state.info.expires_at)}</>
            )}
          </p>
          <p>
            <a
              href={publicShareDownloadUrl(token!)}
              style={{
                display: "inline-block",
                padding: "0.5rem 1rem",
                background: "#1f883d",
                color: "white",
                borderRadius: "4px",
                textDecoration: "none",
              }}
            >
              Download
            </a>
          </p>
        </div>
      )}
    </main>
  );
}
