import { apiClient } from "@/api/client";

export type Role = "admin" | "user" | "guest";
export type UserStatus = "active" | "disabled" | "locked";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
  status: UserStatus;
  is_manager: boolean;
  department_id: string | null;
  department: string | null;
  created_at: string;
  last_login_at: string | null;
  two_factor_enabled: boolean;
  // Phase 12
  quota_bytes: number;
  used_bytes: number;
}

export type LoginResult = { kind: "complete"; user: CurrentUser } | { kind: "requires_totp" };

export async function fetchCsrfToken(): Promise<string> {
  const { data } = await apiClient.get<{ csrf_token: string }>("/api/auth/csrf");
  return data.csrf_token;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const { data } = await apiClient.post<CurrentUser | { requires_totp: true }>("/api/auth/login", {
    email,
    password,
  });
  if (data && typeof data === "object" && "requires_totp" in data) {
    return { kind: "requires_totp" };
  }
  return { kind: "complete", user: data as CurrentUser };
}

export async function submitTotpChallenge(code: string): Promise<CurrentUser> {
  const { data } = await apiClient.post<CurrentUser>("/api/auth/totp/challenge", { code });
  return data;
}

export async function logout(): Promise<void> {
  await apiClient.post("/api/auth/logout", {});
}

export async function fetchMe(): Promise<CurrentUser | null> {
  try {
    const { data } = await apiClient.get<CurrentUser>("/api/auth/me");
    return data;
  } catch {
    return null;
  }
}

// --- Phase 6: TOTP enrollment ---

export interface TotpStatus {
  enabled: boolean;
  pending_enrollment: boolean;
  remaining_recovery_codes: number;
  last_used_at: string | null;
}

export interface TotpSetupBundle {
  otpauth_uri: string;
  secret: string;
  recovery_codes: string[];
}

export async function fetchTotpStatus(): Promise<TotpStatus> {
  const { data } = await apiClient.get<TotpStatus>("/api/auth/totp/status");
  return data;
}

export async function startTotpSetup(): Promise<TotpSetupBundle> {
  const { data } = await apiClient.post<TotpSetupBundle>("/api/auth/totp/setup", {});
  return data;
}

export async function verifyTotpSetup(code: string): Promise<void> {
  await apiClient.post("/api/auth/totp/verify", { code });
}

export async function disableTotp(code: string): Promise<void> {
  await apiClient.post("/api/auth/totp/disable", { code });
}

export async function register(email: string, password: string): Promise<CurrentUser> {
  const { data } = await apiClient.post<CurrentUser>("/api/auth/register", {
    email,
    password,
  });
  return data;
}
