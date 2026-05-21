import { apiClient } from "@/api/client";
import { Role, UserStatus } from "@/api/auth";

// --- Users ---

export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  status: UserStatus;
  is_manager: boolean;
  department_id: string | null;
  department: string | null;
  quota_bytes: number;
  used_bytes: number;
  created_at: string;
  last_login_at: string | null;
  session_invalid_before: string | null;
}

export interface AdminUserUpdate {
  role?: Role;
  department_id?: string | null;
  clear_department?: boolean;
  quota_bytes?: number;
  status?: UserStatus;
  is_manager?: boolean;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<{ items: AdminUser[] }>("/api/admin/users");
  return data.items;
}

export async function getUser(id: string): Promise<AdminUser> {
  const { data } = await apiClient.get<AdminUser>(`/api/admin/users/${id}`);
  return data;
}

export async function updateUser(id: string, body: AdminUserUpdate): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/api/admin/users/${id}`, body);
  return data;
}

export async function forceLogout(id: string): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>(
    `/api/admin/users/${id}/force-logout`,
    {},
  );
  return data;
}

export interface AuditRow {
  id: string;
  timestamp: string;
  action_type: string;
  severity: "info" | "warning" | "critical";
  actor_user_id: string | null;
  actor_ip: string | null;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
}

export async function userAudit(id: string, limit = 100): Promise<AuditRow[]> {
  const { data } = await apiClient.get<{ items: AuditRow[] }>(
    `/api/admin/users/${id}/audit`,
    { params: { limit } },
  );
  return data.items;
}

// --- Departments ---

export interface AdminDepartment {
  id: string;
  name: string;
  created_at: string;
}

export async function listDepartments(): Promise<AdminDepartment[]> {
  const { data } = await apiClient.get<{ items: AdminDepartment[] }>(
    "/api/admin/departments",
  );
  return data.items;
}

export async function createDepartment(name: string): Promise<AdminDepartment> {
  const { data } = await apiClient.post<AdminDepartment>("/api/admin/departments", {
    name,
  });
  return data;
}

export async function renameDepartment(id: string, name: string): Promise<AdminDepartment> {
  const { data } = await apiClient.patch<AdminDepartment>(
    `/api/admin/departments/${id}`,
    { name },
  );
  return data;
}

export async function deleteDepartment(id: string): Promise<void> {
  await apiClient.delete(`/api/admin/departments/${id}`);
}

// --- Groups ---

export interface AdminGroupMember {
  id: string;
  email: string;
  role: Role;
}

export interface AdminGroup {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  members?: AdminGroupMember[];
}

export async function listGroups(): Promise<AdminGroup[]> {
  const { data } = await apiClient.get<{ items: AdminGroup[] }>("/api/admin/groups");
  return data.items;
}

export async function getGroup(id: string): Promise<AdminGroup> {
  const { data } = await apiClient.get<AdminGroup>(`/api/admin/groups/${id}`);
  return data;
}

export async function createGroup(
  name: string,
  description: string | null = null,
): Promise<AdminGroup> {
  const { data } = await apiClient.post<AdminGroup>("/api/admin/groups", {
    name,
    description,
  });
  return data;
}

export async function updateGroup(
  id: string,
  body: { name?: string; description?: string | null; clear_description?: boolean },
): Promise<AdminGroup> {
  const { data } = await apiClient.patch<AdminGroup>(`/api/admin/groups/${id}`, body);
  return data;
}

export async function deleteGroup(id: string): Promise<void> {
  await apiClient.delete(`/api/admin/groups/${id}`);
}

export async function addGroupMember(groupId: string, userId: string): Promise<AdminGroup> {
  const { data } = await apiClient.post<AdminGroup>(
    `/api/admin/groups/${groupId}/members/${userId}`,
    {},
  );
  return data;
}

export async function removeGroupMember(groupId: string, userId: string): Promise<void> {
  await apiClient.delete(`/api/admin/groups/${groupId}/members/${userId}`);
}

// --- Reclassify ---

export interface ReclassifyResponse {
  file_id: string;
  classification_version: number;
  status: string;
}

export async function reclassifyFile(fileId: string): Promise<ReclassifyResponse> {
  const { data } = await apiClient.post<ReclassifyResponse>(
    `/api/admin/files/${fileId}/reclassify`,
    {},
  );
  return data;
}

// --- Policies (Phase 5 endpoints, exposed here for the admin UI) ---

export type Tier = "public" | "internal" | "confidential" | "restricted";

export interface AdminPolicy {
  id: string;
  role: Role;
  department_id: string | null;
  department: string | null;
  allowed_max_tier: Tier;
  allowed_categories: string[] | null;
  denied_categories: string[] | null;
  description: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export async function listPolicies(): Promise<AdminPolicy[]> {
  const { data } = await apiClient.get<{ items: AdminPolicy[] }>("/api/admin/policies");
  return data.items;
}

export interface CreatePolicyRequest {
  role: Role;
  department_id?: string | null;
  allowed_max_tier: Tier;
  allowed_categories?: string[] | null;
  denied_categories?: string[] | null;
  description?: string | null;
}

export async function createPolicy(body: CreatePolicyRequest): Promise<AdminPolicy> {
  const { data } = await apiClient.post<AdminPolicy>("/api/admin/policies", body);
  return data;
}

export async function updatePolicy(
  id: string,
  body: Partial<{
    allowed_max_tier: Tier;
    allowed_categories: string[] | null;
    denied_categories: string[] | null;
    description: string | null;
    clear_allowed_categories: boolean;
    clear_denied_categories: boolean;
    clear_description: boolean;
    clear_department: boolean;
  }>,
): Promise<AdminPolicy> {
  const { data } = await apiClient.patch<AdminPolicy>(`/api/admin/policies/${id}`, body);
  return data;
}

export async function deletePolicy(id: string): Promise<void> {
  await apiClient.delete(`/api/admin/policies/${id}`);
}

// --- Events (Phase 11 ECS stream) ---

export interface AdminEventEnvelope {
  "@timestamp": string;
  event: {
    action: string;
    category: string[];
    type?: string[];
    outcome: string;
    severity: number;
    id: string;
  };
  service: { name: string; type: string };
  log: { level: string };
  message: string;
  user?: { id?: string; email?: string };
  source?: { ip?: string };
  file?: {
    id?: string;
    name?: string;
    size?: number;
    mime_type?: string;
    hash?: { sha256?: string };
  };
  labels: {
    target_type: string | null;
    target_id: string | null;
    metadata?: Record<string, unknown>;
  };
}

export interface EventQuery {
  since?: string;
  until?: string;
  action?: string;
  severity?: "info" | "warning" | "critical";
  limit?: number;
}

export async function listEvents(q: EventQuery = {}): Promise<{
  items: AdminEventEnvelope[];
  count: number;
  queried_at: string;
}> {
  const params: Record<string, string | number> = {};
  if (q.since) params.since = q.since;
  if (q.until) params.until = q.until;
  if (q.action) params.action = q.action;
  if (q.severity) params.severity = q.severity;
  if (q.limit) params.limit = q.limit;
  const { data } = await apiClient.get<{
    items: AdminEventEnvelope[];
    count: number;
    queried_at: string;
  }>("/api/admin/events", { params });
  return data;
}
