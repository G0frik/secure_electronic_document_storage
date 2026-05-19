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
}

export async function fetchCsrfToken(): Promise<string> {
  const { data } = await apiClient.get<{ csrf_token: string }>("/api/auth/csrf");
  return data.csrf_token;
}

export async function login(email: string, password: string): Promise<CurrentUser> {
  const { data } = await apiClient.post<CurrentUser>("/api/auth/login", { email, password });
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
