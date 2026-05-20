import { apiClient } from "@/api/client";

export interface Folder {
  id: string;
  name: string;
  owner_id: string;
  parent_id: string | null;
  created_at: string;
}

export async function listFolders(): Promise<Folder[]> {
  const { data } = await apiClient.get<{ items: Folder[] }>("/api/folders");
  return data.items;
}

export async function createFolder(name: string, parentId: string | null = null): Promise<Folder> {
  const { data } = await apiClient.post<Folder>("/api/folders", {
    name,
    parent_id: parentId,
  });
  return data;
}

export async function deleteFolder(folderId: string): Promise<void> {
  await apiClient.delete(`/api/folders/${folderId}`);
}
