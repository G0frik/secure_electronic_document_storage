import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { useAuth } from "@/state/auth";
import { fetchCsrfToken, register } from "@/api/auth";
import { Lock } from "@/components/icons";

/**
 * Public registration page.
 *
 * Captures email, password, and password confirmation.
 * Enforces length and HIBP policies via backend validation.
 * Auto-logs in on successful creation.
 */
export default function RegisterPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If already logged in, redirect to home
  if (user) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      // 1. Fetch fresh CSRF token
      await fetchCsrfToken();

      // 2. Perform registration
      await register(email, password);

      // 3. Auto-login on success
      const outcome = await login(email, password);
      if (outcome === "requires_totp") {
        navigate("/login", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    } catch (err) {
      const axiosErr = err as AxiosError<{ message?: string; error?: string; code?: string }>;
      setError(axiosErr.response?.data?.message ?? "Registration failed. Please try again.");
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

        <h1>Create account</h1>
        <p className="auth-card-subtitle">Register a new account to store documents securely.</p>

        <form onSubmit={onSubmit} className="auth-form">
          <div className="field">
            <label className="field-label" htmlFor="register-email">
              Email
            </label>
            <input
              id="register-email"
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="email"
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="register-password">
              Password
            </label>
            <input
              id="register-password"
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="Min. 12 characters"
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="register-confirm-password">
              Confirm Password
            </label>
            <input
              id="register-confirm-password"
              className="input"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
            />
          </div>
          {error && (
            <p className="field-error" style={{ whiteSpace: "pre-line" }}>
              {error}
            </p>
          )}
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting}
            style={{ width: "100%", height: 38 }}
          >
            {submitting ? "Creating account…" : "Register"}
          </button>
        </form>

        <div style={{ marginTop: "var(--space-4)", textAlign: "center" }}>
          <p className="text-small text-muted">
            Already have an account?{" "}
            <Link to="/login" className="link" style={{ fontWeight: 500 }}>
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
