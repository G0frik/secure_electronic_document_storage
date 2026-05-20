import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { useAuth } from "@/state/auth";

interface LocationState {
  from?: string;
}

type Step = "password" | "totp";

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
    <main>
      <h1>Sign in</h1>
      <p>Secure Document Storage</p>

      {step === "password" && (
        <form onSubmit={onPasswordSubmit}>
          <p>
            <label>
              Email
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
              Password
              <br />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={1}
                style={{ width: "100%", padding: "0.5rem" }}
              />
            </label>
          </p>
          {error && <p className="status-fail">{error}</p>}
          <p>
            <button type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </p>
        </form>
      )}

      {step === "totp" && (
        <form onSubmit={onTotpSubmit}>
          <p>Enter the 6-digit code from your authenticator app (or a recovery code).</p>
          <p>
            <label>
              Code
              <br />
              <input
                type="text"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                required
                autoFocus
                inputMode="numeric"
                pattern="[0-9A-Za-z\-]*"
                style={{ width: "100%", padding: "0.5rem", letterSpacing: "0.2em" }}
              />
            </label>
          </p>
          {error && <p className="status-fail">{error}</p>}
          <p style={{ display: "flex", gap: "0.5rem" }}>
            <button type="submit" disabled={submitting || !totpCode}>
              {submitting ? "Verifying…" : "Verify"}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep("password");
                setTotpCode("");
                setPassword("");
                setError(null);
              }}
            >
              Start over
            </button>
          </p>
        </form>
      )}
    </main>
  );
}
