import { apiClient } from "@/api/client";

export type HealthStatus = {
  status: string;
};

export async function fetchHealth(): Promise<HealthStatus> {
  const { data } = await apiClient.get<HealthStatus>("/healthz");
  return data;
}
