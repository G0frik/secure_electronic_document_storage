import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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

export default function SecuritySettingsPage() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();

  const [status, setStatus] = useState<TotpStatus | null>(null);
  const [setupBundle, setSetupBundle] = useState<TotpSetupBundle | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchTotpStatus().then(setStatus).catch(() => setStatus(null));
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
    <main>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          borderBottom: "1px solid #eaeef2",
          paddingBottom: "0.75rem",
          marginBottom: "1.25rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Security settings</h1>
        <button onClick={() => navigate("/")}>← Back to files</button>
      </header>

      <p style={{ color: "#6e7781" }}>
        Signed in as <strong>{user?.email}</strong>
      </p>

      {error && <p className="status-fail">{error}</p>}
      {info && <p className="status-ok">{info}</p>}

      <section style={{ marginTop: "1.5rem" }}>
        <h2>Two-factor authentication (TOTP)</h2>

        {status === null ? (
          <p className="status-pending">Loading status…</p>
        ) : status.enabled ? (
          <>
            <p>
              Status: <span className="status-ok">enabled</span>
              {status.last_used_at && (
                <> · last used {new Date(status.last_used_at).toLocaleString()}</>
              )}
            </p>
            <p>Remaining recovery codes: {status.remaining_recovery_codes} / 10</p>

            <form onSubmit={onDisable} style={{ marginTop: "1rem" }}>
              <p>Disable 2FA — enter a current TOTP code or one of your recovery codes:</p>
              <p>
                <input
                  type="text"
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  required
                  style={{ width: "16rem", padding: "0.5rem" }}
                  placeholder="123456 or XXXX-XXXX-XXXX"
                />{" "}
                <button type="submit" disabled={busy || !disableCode}>
                  Disable 2FA
                </button>
              </p>
            </form>
          </>
        ) : (
          <>
            <p>
              Status: <span className="status-fail">disabled</span>
              {status.pending_enrollment && <> · enrolment started but not verified</>}
            </p>

            {!setupBundle && (
              <p>
                <button onClick={onBeginSetup} disabled={busy}>
                  {status.pending_enrollment ? "Re-generate QR" : "Enable 2FA"}
                </button>
              </p>
            )}

            {setupBundle && (
              <div style={{ marginTop: "1rem" }}>
                <p>1. Scan this QR with your authenticator app (or paste the secret manually):</p>
                <div
                  style={{
                    background: "white",
                    padding: "1rem",
                    width: "fit-content",
                    border: "1px solid #d0d7de",
                  }}
                >
                  <QRCodeSVG value={setupBundle.otpauth_uri} size={192} />
                </div>
                <p style={{ marginTop: "0.5rem" }}>
                  <small>
                    Manual entry secret: <code>{setupBundle.secret}</code>
                  </small>
                </p>

                <p style={{ marginTop: "1rem" }}>
                  2. Save these <strong>recovery codes</strong> somewhere safe — each works once and
                  is your only fallback if you lose your phone. They will not be shown again.
                </p>
                <pre
                  style={{
                    background: "#f6f8fa",
                    padding: "0.75rem",
                    border: "1px solid #d0d7de",
                    fontFamily: "Consolas, monospace",
                    fontSize: "0.95em",
                  }}
                >
                  {setupBundle.recovery_codes.join("\n")}
                </pre>
                <p>
                  <button
                    type="button"
                    onClick={() =>
                      navigator.clipboard
                        ?.writeText(setupBundle.recovery_codes.join("\n"))
                        .then(() => setInfo("Recovery codes copied to clipboard."))
                    }
                  >
                    Copy recovery codes
                  </button>
                </p>

                <form onSubmit={onVerify} style={{ marginTop: "1rem" }}>
                  <p>3. Enter the 6-digit code from your authenticator to finish enrolment:</p>
                  <p>
                    <input
                      type="text"
                      value={verifyCode}
                      onChange={(e) => setVerifyCode(e.target.value)}
                      required
                      inputMode="numeric"
                      pattern="[0-9]*"
                      style={{ width: "12rem", padding: "0.5rem", letterSpacing: "0.2em" }}
                      placeholder="123456"
                    />{" "}
                    <button type="submit" disabled={busy || !verifyCode}>
                      Verify and enable
                    </button>
                  </p>
                </form>
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
