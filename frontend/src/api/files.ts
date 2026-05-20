import { AxiosError } from "axios";
import { apiClient } from "@/api/client";

export interface AccessDeniedPayload {
  error: "access_denied";
  reason: string;
  tier: Tier | null;
  message: string;
}

export class AccessDeniedError extends Error {
  reason: string;
  tier: Tier | null;
  constructor(payload: AccessDeniedPayload) {
    super(payload.message);
    this.name = "AccessDeniedError";
    this.reason = payload.reason;
    this.tier = payload.tier;
  }
}

export interface StoredFile {
  id: string;
  owner_id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
}

export interface FileListResponse {
  items: StoredFile[];
  page: number;
  per_page: number;
  total: number;
}

export type ClassificationStatus = "pending" | "running" | "completed" | "failed" | "missing";
export type Tier = "public" | "internal" | "confidential" | "restricted";

export interface ClassificationResult {
  file_id: string;
  version: number;
  status: ClassificationStatus;
  final_tier: Tier | null;
  zero_shot_tier: Tier | null;
  presidio_tier: Tier | null;
  categories_triggered: string[] | null;
  raw_scores: Record<string, number> | null;
  presidio_entities: Record<string, { count: number; max_score: number; samples: string[] }> | null;
  classifier_version: string | null;
  error_message: string | null;
  created_at: string | null;
  classified_at: string | null;
}

export async function fetchClassification(fileId: string): Promise<ClassificationResult> {
  const { data } = await apiClient.get<ClassificationResult>(
    `/api/files/${fileId}/classification`,
  );
  return data;
}

export async function listFiles(page = 1, perPage = 50): Promise<FileListResponse> {
  const { data } = await apiClient.get<FileListResponse>("/api/files", {
    params: { page, per_page: perPage },
  });
  return data;
}

export async function uploadFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<StoredFile> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<StoredFile>("/api/files", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    },
  });
  return data;
}

export function downloadFileUrl(fileId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  return `${base}/api/files/${fileId}/download`;
}

export async function downloadFile(file: StoredFile): Promise<void> {
  try {
    const response = await apiClient.get<Blob>(`/api/files/${file.id}/download`, {
      responseType: "blob",
    });
    const blob = response.data;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.original_filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    // 403 bodies come back as a Blob (because we asked for responseType:"blob");
    // parse it back to JSON so callers see the policy reason.
    if (err instanceof AxiosError && err.response?.status === 403) {
      const text = await (err.response.data as Blob).text();
      try {
        const payload = JSON.parse(text) as AccessDeniedPayload;
        throw new AccessDeniedError(payload);
      } catch (parseErr) {
        if (parseErr instanceof AccessDeniedError) throw parseErr;
      }
    }
    throw err;
  }
}
