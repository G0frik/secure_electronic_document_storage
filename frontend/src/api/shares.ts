import { apiClient } from "@/api/client";

export type ShareTargetType = "file" | "folder";
export type SharePermission = "viewer" | "editor";

export interface Share {
  id: string;
  target_type: ShareTargetType;
  target_id: string;
  granter_id: string;
  recipient_id: string;
  permission: SharePermission;
  created_at: string;
  revoked_at: string | null;
  // Decorated by the server for convenience
  label: string;
  kind: ShareTargetType;
  granter_email?: string;
  recipient_email?: string;
}

export interface CreateShareRequest {
  target_type: ShareTargetType;
  target_id: string;
  recipient_email: string;
  permission?: SharePermission;
}

export async function createShare(req: CreateShareRequest): Promise<Share> {
  const { data } = await apiClient.post<Share>("/api/shares", req);
  return data;
}

export async function listReceived(): Promise<Share[]> {
  const { data } = await apiClient.get<{ items: Share[] }>("/api/shares/received");
  return data.items;
}

export async function listGranted(): Promise<Share[]> {
  const { data } = await apiClient.get<{ items: Share[] }>("/api/shares/granted");
  return data.items;
}

export async function revokeShare(shareId: string): Promise<void> {
  await apiClient.delete(`/api/shares/${shareId}`);
}
