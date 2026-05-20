import { apiClient } from "@/api/client";

export interface Tag {
  id: string;
  name: string;
  created_at: string;
}

export async function listTags(fileId: string): Promise<Tag[]> {
  const { data } = await apiClient.get<{ items: Tag[] }>(
    `/api/files/${fileId}/tags`,
  );
  return data.items;
}

export async function addTags(fileId: string, names: string[]): Promise<Tag[]> {
  const { data } = await apiClient.post<{ items: Tag[] }>(
    `/api/files/${fileId}/tags`,
    { names },
  );
  return data.items;
}

export async function removeTag(fileId: string, tagId: string): Promise<void> {
  await apiClient.delete(`/api/files/${fileId}/tags/${tagId}`);
}
