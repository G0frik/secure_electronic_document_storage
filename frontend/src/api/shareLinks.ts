import { apiClient } from "@/api/client";

export interface ShareLink {
  id: string;
  file_id: string;
  filename: string | null;
  expires_at: string | null;
  max_uses: number | null;
  use_count: number;
  created_at: string;
  revoked_at: string | null;
  created_by_id: string | null;
  /** Plaintext token — only present in the create response. */
  token: string | null;
}

export interface CreateShareLinkRequest {
  file_id: string;
  expires_at?: string | null;
  max_uses?: number | null;
  force_for_restricted?: boolean;
}

export async function createShareLink(req: CreateShareLinkRequest): Promise<ShareLink> {
  const { data } = await apiClient.post<ShareLink>("/api/share-links", req);
  return data;
}

export async function listGrantedLinks(): Promise<ShareLink[]> {
  const { data } = await apiClient.get<{ items: ShareLink[] }>("/api/share-links/granted");
  return data.items;
}

export async function revokeShareLink(linkId: string): Promise<void> {
  await apiClient.delete(`/api/share-links/${linkId}`);
}

// --- Public consumer endpoints (no auth required) ---

export interface PublicShareLinkInfo {
  filename: string;
  mime_type: string;
  size_bytes: number;
  expires_at: string | null;
  max_uses: number | null;
  use_count: number;
  remaining_uses: number | null;
}

export interface PublicShareLinkInvalid {
  error: "not_found" | "invalid";
  reason?: "revoked" | "expired" | "exhausted";
}

/**
 * Resolves the public link metadata. Returns null when the link is missing/invalid,
 * along with the reason via the second tuple element so the UI can render
 * "this link has been revoked" / "this link has expired" / etc.
 */
export async function fetchPublicShareLink(
  token: string,
): Promise<{ info: PublicShareLinkInfo | null; invalid?: PublicShareLinkInvalid }> {
  try {
    const { data } = await apiClient.get<PublicShareLinkInfo>(`/api/public/share-links/${token}`);
    return { info: data };
  } catch (err) {
    const ax = err as { response?: { status?: number; data?: PublicShareLinkInvalid } };
    return { info: null, invalid: ax.response?.data };
  }
}

export function publicShareDownloadUrl(token: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  return `${base}/api/public/share-links/${token}/download`;
}
