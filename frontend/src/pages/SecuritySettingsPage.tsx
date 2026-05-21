import { FormEvent, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QRCodeSVG } from "qrcode.react";
import {
  TotpSetupBundle,
  TotpStatus,
  disableTotp,
  fetchTotpStatus,
  startTotpSetup,
  verifyTotpSetup,
} from "@/api/auth";
import { useAuth } from "@/state/auth";
import Breadcrumb from "@/components/Breadcrumb";
import { CheckCircle2, ShieldCheck, XCircle } from "@/components/icons";

/**
 * Security settings — one card per concern.
 *
 * Today: TOTP enrolment + disable. Password change and active-sessions
 * UI are listed as "future work" placeholders in the body so users can
 * see what's coming. Renders inside AppShell.
 */
export default function SecuritySettingsPage() {
  const { user, refresh } = useAuth();

  const [status, setStatus] = useState<TotpStatus | null>(null);
  const [setupBundle, setSetupBundle] = useState<TotpSetupBundle | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchTotpStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  async function refreshStatus() {
    const next = await fetchTotpStatus();
    setStatus(next);
    await refresh();
  }

  async function onBeginSetup() {
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      const bundle = await startTotpSetup();
      setSetupBundle(bundle);
      await refreshStatus();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Could not start setup.");
    } finally {
      setBusy(false);
    }
  }

  async function onVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await verifyTotpSetup(verifyCode);
      setSetupBundle(null);
      setVerifyCode("");
      setInfo("Two-factor authentication is now enabled.");
      await refreshStatus();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Verification failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onDisable(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await disableTotp(disableCode);
      setDisableCode("");
      setInfo("Two-factor authentication is now disabled.");
      await refreshStatus();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Disable failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Security" }]} />

      <div className="page-header">
        <div className="page-title">
          <h1>Security</h1>
          <span className="page-subtitle">
            Signed in as <span className="text-mono">{user?.email}</span>
          </span>
        </div>
      </div>

      {error && <p className="field-error">{error}</p>}
      {info && (
        <p className="row row-2" style={{ color: "var(--color-success)" }}>
          <CheckCircle2 size={14} /> {info}
        </p>
      )}

      {/* --- TOTP card --- */}
      <div className="card" style={{ marginBottom: "var(--space-5)" }}>
        <div className="card-header row row-2">
          <ShieldCheck size={16} />
          Two-factor authentication
        </div>
        <div className="card-body">
          {status === null && <p className="text-muted">Loading status…</p>}

          {status?.enabled && (
            <>
              <p
                className="row row-2"
                style={{ color: "var(--color-success)" }}
              >
                <CheckCircle2 size={14} />
                <span>2FA is enabled on this account.</span>
              </p>
              {status.last_used_at && (
                <p className="text-small text-muted">
                  Last used {new Date(status.last_used_at).toLocaleString()}
                </p>
              )}
              <p className="text-small text-muted">
                Remaining recovery codes: {status.remaining_recovery_codes} / 10
              </p>

              <hr className="divider" />

              <form onSubmit={onDisable} className="stack stack-3">
                <div className="field">
                  <label className="field-label">
                    Disable 2FA — enter a current TOTP code or a recovery code
                  </label>
                  <input
                    type="text"
                    className="input text-mono"
                    value={disableCode}
                    onChange={(e) => setDisableCode(e.target.value)}
                    required
                    style={{ maxWidth: 280, letterSpacing: "0.15em" }}
                    placeholder="123456 or XXXX-XXXX-XXXX"
                  />
                </div>
                <div>
                  <button
                    type="submit"
                    className="btn btn-danger"
                    disabled={busy || !disableCode}
                  >
                    Disable 2FA
                  </button>
                </div>
              </form>
            </>
          )}

          {status && !status.enabled && (
            <>
              <p
                className="row row-2"
                style={{ color: "var(--color-muted)" }}
              >
                <XCircle size={14} />
                <span>
                  2FA is not enabled.
                  {status.pending_enrollment &&
                    " An enrolment was started but never verified."}
                </span>
              </p>

              {!setupBundle && (
                <p style={{ marginTop: "var(--space-3)" }}>
                  <button
                    className="btn btn-primary"
                    onClick={onBeginSetup}
                    disabled={busy}
                  >
                    {status.pending_enrollment
                      ? "Re-generate QR code"
                      : "Enable 2FA"}
                  </button>
                </p>
              )}

              {setupBundle && (
                <div className="stack stack-4" style={{ marginTop: "var(--space-3)" }}>
                  <div>
                    <strong>1. Scan this QR code</strong> with your authenticator
                    app, or paste the secret manually.
                    <div
                      style={{
                        marginTop: "var(--space-3)",
                        padding: "var(--space-4)",
                        background: "var(--color-surface)",
                        border: "1px solid var(--color-line)",
                        borderRadius: "var(--radius-md)",
                        width: "fit-content",
                      }}
                    >
                      <QRCodeSVG value={setupBundle.otpauth_uri} size={184} />
                    </div>
                    <p
                      className="text-small text-muted"
                      style={{ marginTop: "var(--space-2)" }}
                    >
                      Manual entry secret:{" "}
                      <code>{setupBundle.secret}</code>
                    </p>
                  </div>

                  <div>
                    <strong>2. Save your recovery codes</strong> somewhere safe.
                    Each works once. They will not be shown again.
                    <pre
                      style={{
                        marginTop: "var(--space-2)",
                        padding: "var(--space-3)",
                        background: "var(--color-surface-2)",
                        border: "1px solid var(--color-line)",
                        borderRadius: "var(--radius-sm)",
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.875rem",
                      }}
                    >
                      {setupBundle.recovery_codes.join("\n")}
                    </pre>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() =>
                        navigator.clipboard
                          ?.writeText(setupBundle.recovery_codes.join("\n"))
                          .then(() =>
                            setInfo("Recovery codes copied to clipboard."),
                          )
                      }
                    >
                      Copy recovery codes
                    </button>
                  </div>

                  <form onSubmit={onVerify} className="stack stack-3">
                    <div className="field">
                      <label className="field-label">
                        3. Enter the 6-digit code from your authenticator
                      </label>
                      <input
                        type="text"
                        className="input text-mono"
                        value={verifyCode}
                        onChange={(e) => setVerifyCode(e.target.value)}
                        required
                        inputMode="numeric"
                        pattern="[0-9]*"
                        placeholder="123456"
                        style={{ maxWidth: 200, letterSpacing: "0.2em" }}
                      />
                    </div>
                    <div>
                      <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={busy || !verifyCode}
                      >
                        Verify and enable
                      </button>
                    </div>
                  </form>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
