import { apiClient } from "@/api/client";

export type Severity = "info" | "warning" | "critical";

export interface AppNotification {
  id: string;
  action_type: string;
  title: string;
  body: string | null;
  severity: Severity;
  audit_log_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: AppNotification[];
  unread_count: number;
}

export async function listNotifications(
  opts: { unread?: boolean; limit?: number } = {},
): Promise<NotificationListResponse> {
  const params: Record<string, string | number> = {};
  if (opts.unread) params.unread = "true";
  if (opts.limit) params.limit = opts.limit;
  const { data } = await apiClient.get<NotificationListResponse>(
    "/api/notifications",
    { params },
  );
  return data;
}

export async function unreadCount(): Promise<number> {
  const { data } = await apiClient.get<{ unread_count: number }>(
    "/api/notifications/unread-count",
  );
  return data.unread_count;
}

export async function markRead(id: string): Promise<AppNotification> {
  const { data } = await apiClient.post<AppNotification>(
    `/api/notifications/${id}/read`,
    {},
  );
  return data;
}

export async function markAllRead(): Promise<number> {
  const { data } = await apiClient.post<{ marked_read: number }>(
    "/api/notifications/read-all",
    {},
  );
  return data.marked_read;
}
