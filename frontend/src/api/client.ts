import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

const MUTATING_METHODS = new Set(["post", "put", "patch", "delete"]);

function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]!) : null;
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = (config.method ?? "get").toLowerCase();
  if (MUTATING_METHODS.has(method)) {
    const token = readCsrfCookie();
    if (token) {
      config.headers.set("X-CSRF-Token", token);
    }
  }
  return config;
});

const onUnauthorized: Array<() => void> = [];

export function registerUnauthorizedHandler(fn: () => void): () => void {
  onUnauthorized.push(fn);
  return () => {
    const idx = onUnauthorized.indexOf(fn);
    if (idx >= 0) onUnauthorized.splice(idx, 1);
  };
}

apiClient.interceptors.response.use(
  (r) => r,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      onUnauthorized.forEach((fn) => fn());
    }
    return Promise.reject(error);
  },
);
