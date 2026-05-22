import { FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { useAuth } from "@/state/auth";
import { Lock } from "@/components/icons";

interface LocationState {
  from?: string;
}

type Step = "password" | "totp";

/**
 * Sign-in page.
 *
 * Two-step flow: email + password → optional TOTP challenge. Renders as a
 * centered card on the warm paper-tone background. No AppShell — public
 * route.
 */
export default function LoginPage() {
  const { user, login, submitTotpCode } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<Step>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  function navigateNext() {
    const dest = (location.state as LocationState | null)?.from ?? "/";
    navigate(dest, { replace: true });
  }

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const outcome = await login(email, password);
      if (outcome === "requires_totp") {
        setStep("totp");
      } else {
        navigateNext();
      }
    } catch (err) {
      const axiosErr = err as AxiosError<{ message?: string }>;
      setError(axiosErr.response?.data?.message ?? "Login failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function onTotpSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await submitTotpCode(totpCode);
      navigateNext();
    } catch (err) {
      const axiosErr = err as AxiosError<{ message?: string }>;
      setError(axiosErr.response?.data?.message ?? "Invalid code. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="row row-2" style={{ marginBottom: "var(--space-3)" }}>
          <span className="topbar-brand-mark" aria-hidden="true">
            <Lock size={14} strokeWidth={2.5} />
          </span>
          <span
            className="text-mono text-small text-muted"
            style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}
          >
            Secure Docs
          </span>
        </div>

        {step === "password" && (
          <>
            <h1>Sign in</h1>
            <p className="auth-card-subtitle">Use your work email and password.</p>

            <form onSubmit={onPasswordSubmit} className="auth-form">
              <div className="field">
                <label className="field-label" htmlFor="login-email">
                  Email
                </label>
                <input
                  id="login-email"
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="login-password">
                  Password
                </label>
                <input
                  id="login-password"
                  className="input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
              </div>
              {error && <p className="field-error">{error}</p>}
              <button
                type="submit"
                className="btn btn-primary"
                disabled={submitting}
                style={{ width: "100%", height: 38 }}
              >
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>

            <div style={{ marginTop: "var(--space-4)", textAlign: "center" }}>
              <p className="text-small text-muted">
                Don't have an account?{" "}
                <Link to="/register" className="link" style={{ fontWeight: 500 }}>
                  Create one
                </Link>
              </p>
            </div>
          </>
        )}

        {step === "totp" && (
          <>
            <h1>Two-factor code</h1>
            <p className="auth-card-subtitle">
              Enter the 6-digit code from your authenticator app, or one of your recovery codes.
            </p>

            <form onSubmit={onTotpSubmit} className="auth-form">
              <div className="field">
                <label className="field-label" htmlFor="login-totp">
                  Code
                </label>
                <input
                  id="login-totp"
                  className="input text-mono"
                  type="text"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  required
                  autoFocus
                  inputMode="numeric"
                  pattern="[0-9A-Za-z\-]*"
                  style={{ letterSpacing: "0.2em" }}
                />
              </div>
              {error && <p className="field-error">{error}</p>}
              <div className="row row-2">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitting || !totpCode}
                  style={{ flex: 1, height: 38 }}
                >
                  {submitting ? "Verifying…" : "Verify"}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setStep("password");
                    setTotpCode("");
                    setPassword("");
                    setError(null);
                  }}
                  style={{ height: 38 }}
                >
                  Start over
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
