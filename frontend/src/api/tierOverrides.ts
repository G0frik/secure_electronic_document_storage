import { apiClient } from "@/api/client";

export type Tier = "public" | "internal" | "confidential" | "restricted";
export type OverrideStatus = "pending" | "approved" | "denied";

export interface TierOverrideRequest {
  id: string;
  file_id: string;
  filename: string | null;
  classification_id: string | null;
  requested_by_id: string;
  requested_by_email: string | null;
  current_tier: Tier;
  requested_tier: Tier;
  justification: string;
  status: OverrideStatus;
  reviewed_by_id: string | null;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  decision_reason: string | null;
  created_at: string;
}

export async function createOverrideRequest(
  fileId: string,
  requestedTier: Tier,
  justification: string,
): Promise<TierOverrideRequest> {
  const { data } = await apiClient.post<TierOverrideRequest>(
    `/api/files/${fileId}/tier-override-requests`,
    { requested_tier: requestedTier, justification },
  );
  return data;
}

export async function listOverridesForFile(
  fileId: string,
): Promise<TierOverrideRequest[]> {
  const { data } = await apiClient.get<{ items: TierOverrideRequest[] }>(
    `/api/files/${fileId}/tier-override-requests`,
  );
  return data.items;
}

export async function listAdminOverrides(
  status: OverrideStatus | "all" = "pending",
): Promise<TierOverrideRequest[]> {
  const { data } = await apiClient.get<{ items: TierOverrideRequest[] }>(
    `/api/admin/tier-override-requests`,
    { params: { status } },
  );
  return data.items;
}

export async function approveOverride(
  requestId: string,
  decisionReason?: string,
): Promise<TierOverrideRequest> {
  const { data } = await apiClient.post<TierOverrideRequest>(
    `/api/admin/tier-override-requests/${requestId}/approve`,
    { decision_reason: decisionReason ?? null },
  );
  return data;
}

export async function denyOverride(
  requestId: string,
  decisionReason?: string,
): Promise<TierOverrideRequest> {
  const { data } = await apiClient.post<TierOverrideRequest>(
    `/api/admin/tier-override-requests/${requestId}/deny`,
    { decision_reason: decisionReason ?? null },
  );
  return data;
}
