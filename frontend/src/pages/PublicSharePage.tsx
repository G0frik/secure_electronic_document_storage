import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchPublicShareLink,
  PublicShareLinkInfo,
  publicShareDownloadUrl,
} from "@/api/shareLinks";
import { formatBytes, formatDateTime } from "@/utils/format";
import { AlertTriangle, Download, FileText, Lock, XCircle } from "@/components/icons";

type State =
  | { kind: "loading" }
  | { kind: "ok"; info: PublicShareLinkInfo }
  | { kind: "missing" }
  | { kind: "expired" }
  | { kind: "revoked" }
  | { kind: "exhausted" }
  | { kind: "tier_blocked" }
  | { kind: "classification_pending" };

/**
 * Public landing for an external share link.
 *
 * No shell — this is the only thing the unauthenticated visitor sees.
 * Centered card on the paper background; big filename, big Download CTA.
 */
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
      } else if (invalid?.reason === "tier_blocked") {
        setState({ kind: "tier_blocked" });
      } else if (invalid?.reason === "classification_pending") {
        setState({ kind: "classification_pending" });
      } else {
        setState({ kind: "missing" });
      }
    });
  }, [token]);

  return (
    <div className="auth-page">
      <div className="auth-card" style={{ width: "min(480px, 100%)" }}>
        <div className="row row-2" style={{ marginBottom: "var(--space-3)" }}>
          <span className="topbar-brand-mark" aria-hidden="true">
            <Lock size={14} strokeWidth={2.5} />
          </span>
          <span
            className="text-mono text-small text-muted"
            style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}
          >
            Secure Docs · Shared file
          </span>
        </div>

        {state.kind === "loading" && <p className="text-muted">Loading link…</p>}

        {state.kind !== "loading" && state.kind !== "ok" && <InvalidState kind={state.kind} />}

        {state.kind === "ok" && <OkState info={state.info} token={token!} />}
      </div>
    </div>
  );
}

function InvalidState({ kind }: { kind: Exclude<State["kind"], "loading" | "ok"> }) {
  const copy: Record<typeof kind, { title: string; body: string }> = {
    missing: {
      title: "Link not found",
      body: "This share link doesn't exist or has been removed.",
    },
    expired: {
      title: "Link expired",
      body: "This share link has passed its expiry date.",
    },
    revoked: {
      title: "Link revoked",
      body: "The sender has revoked this share link.",
    },
    exhausted: {
      title: "Download limit reached",
      body: "This share link has reached its maximum number of downloads.",
    },
    // Neither message names the tier: it would tell an outsider what the file contains.
    tier_blocked: {
      title: "File not available",
      body: "The current version of this file can't be shared through an external link.",
    },
    classification_pending: {
      title: "File is being checked",
      body: "This file was updated and is still being checked. Try again in a few minutes.",
    },
  };

  const Icon = kind === "missing" ? XCircle : AlertTriangle;
  return (
    <>
      <h1>{copy[kind].title}</h1>
      <p className="row row-2" style={{ color: "var(--color-muted)", marginTop: "var(--space-3)" }}>
        <Icon size={16} />
        <span>{copy[kind].body}</span>
      </p>
    </>
  );
}

function OkState({ info, token }: { info: PublicShareLinkInfo; token: string }) {
  return (
    <>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "var(--space-3)",
          padding: "var(--space-5) 0",
          textAlign: "center",
        }}
      >
        <FileText size={48} className="text-muted" />
        <div className="filename" style={{ fontSize: "1.05rem" }}>
          {info.filename}
        </div>
        <div className="text-small text-muted">
          {formatBytes(info.size_bytes)} · <span className="text-mono">{info.mime_type}</span>
        </div>
      </div>

      <a
        href={publicShareDownloadUrl(token)}
        className="btn btn-primary"
        style={{
          width: "100%",
          height: 40,
          textDecoration: "none",
        }}
      >
        <Download size={16} />
        Download
      </a>

      <p
        className="text-small text-muted"
        style={{ marginTop: "var(--space-3)", textAlign: "center" }}
      >
        {info.max_uses !== null && (
          <>
            {info.remaining_uses}/{info.max_uses} downloads remaining
            {info.expires_at && " · "}
          </>
        )}
        {info.expires_at && <>expires {formatDateTime(info.expires_at)}</>}
      </p>
    </>
  );
}
