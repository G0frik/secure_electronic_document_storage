import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  CurrentUser,
  fetchCsrfToken,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  submitTotpChallenge,
} from "@/api/auth";
import { registerUnauthorizedHandler } from "@/api/client";

export type LoginOutcome = "complete" | "requires_totp";

interface AuthContextValue {
  user: CurrentUser | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<LoginOutcome>;
  submitTotpCode: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetchCsrfToken(); // ensures cookie is set before any mutating call
        const me = await fetchMe();
        if (!cancelled) setUser(me);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return registerUnauthorizedHandler(() => setUser(null));
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<LoginOutcome> => {
    await fetchCsrfToken();
    const result = await apiLogin(email, password);
    if (result.kind === "requires_totp") {
      setUser(null);
      return "requires_totp";
    }
    setUser(result.user);
    return "complete";
  }, []);

  const submitTotpCode = useCallback(async (code: string) => {
    const loggedIn = await submitTotpChallenge(code);
    setUser(loggedIn);
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, isLoading, login, submitTotpCode, logout, refresh }),
    [user, isLoading, login, submitTotpCode, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
