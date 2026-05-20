import { AxiosError } from "axios";
import { apiClient } from "@/api/client";

export type FolderScope = "all" | "folder";

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
  folder_id: string | null;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  deleted_at?: string | null;
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

export interface ListFilesParams {
  page?: number;
  perPage?: number;
  folderScope?: FolderScope;
  folderId?: string | null;
}

export async function listFiles(params: ListFilesParams = {}): Promise<FileListResponse> {
  const { page = 1, perPage = 50, folderScope, folderId } = params;
  const queryParams: Record<string, string | number> = { page, per_page: perPage };
  if (folderScope) queryParams.folder_scope = folderScope;
  if (folderId) queryParams.folder_id = folderId;
  const { data } = await apiClient.get<FileListResponse>("/api/files", {
    params: queryParams,
  });
  return data;
}

export async function listSharedFiles(): Promise<{ items: StoredFile[]; total: number }> {
  const { data } = await apiClient.get<{ items: StoredFile[]; total: number }>(
    "/api/files/shared",
  );
  return data;
}

export async function uploadFile(
  file: File,
  options: { onProgress?: (percent: number) => void; folderId?: string | null } = {},
): Promise<StoredFile> {
  const form = new FormData();
  form.append("file", file);
  if (options.folderId) form.append("folder_id", options.folderId);
  const { data } = await apiClient.post<StoredFile>("/api/files", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (evt) => {
      if (options.onProgress && evt.total) {
        options.onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    },
  });
  return data;
}

export function downloadFileUrl(fileId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  return `${base}/api/files/${fileId}/download`;
}

export async function softDeleteFile(fileId: string): Promise<void> {
  await apiClient.delete(`/api/files/${fileId}`);
}

export interface TrashedFile extends StoredFile {
  deleted_at: string;
}

export async function listTrash(): Promise<TrashedFile[]> {
  const { data } = await apiClient.get<{ items: TrashedFile[] }>("/api/trash");
  return data.items;
}

export async function restoreFile(fileId: string): Promise<TrashedFile> {
  const { data } = await apiClient.post<TrashedFile>(
    `/api/trash/${fileId}/restore`,
    {},
  );
  return data;
}

export async function hardDeleteFile(fileId: string): Promise<void> {
  await apiClient.delete(`/api/trash/${fileId}`);
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
