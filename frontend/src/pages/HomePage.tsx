import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { listFiles, listSharedFiles, StoredFile } from "@/api/files";
import { Folder, listFolders } from "@/api/folders";
import { useAuth } from "@/state/auth";
import Breadcrumb from "@/components/Breadcrumb";
import DropzoneUpload from "@/components/DropzoneUpload";
import FileTable from "@/components/FileTable";

const PER_PAGE = 50;

type TabKey = "mine" | "shared";

/**
 * Home — the main file browser.
 *
 * Renders inside AppShell, so this page just provides the page-level content
 * (breadcrumb, dropzone, tabs, file table). The topbar and sidebar come
 * from the shell; no per-page header, no per-page logout, no inline quota.
 */
export default function HomePage() {
  const { refresh } = useAuth();

  const [tab, setTab] = useState<TabKey>("mine");
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [folders, setFolders] = useState<Folder[]>([]);
  const [uploadFolderId, setUploadFolderId] = useState<string | null>(null);
  const [sharedFiles, setSharedFiles] = useState<StoredFile[]>([]);

  const reload = useCallback(
    async (targetPage = page) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listFiles({ page: targetPage, perPage: PER_PAGE });
        setFiles(data.items);
        setTotal(data.total);
        setPage(data.page);
      } catch (err) {
        const ax = err as AxiosError<{ message?: string }>;
        setError(ax.response?.data?.message ?? "Failed to load files.");
      } finally {
        setLoading(false);
      }
    },
    [page],
  );

  const reloadFolders = useCallback(async () => {
    try {
      const items = await listFolders();
      setFolders(items);
    } catch (err) {
      console.warn("Failed to load folders", err);
    }
  }, []);

  const reloadShared = useCallback(async () => {
    try {
      const { items } = await listSharedFiles();
      setSharedFiles(items);
    } catch (err) {
      console.warn("Failed to load shared files", err);
    }
  }, []);

  useEffect(() => {
    reload(1);
    reloadFolders();
    reloadShared();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page">
      <Breadcrumb items={[{ label: "Home" }]} />

      <div className="page-header">
        <div className="page-title">
          <h1>My files</h1>
          <span className="page-subtitle">
            Drop a file to upload — it's encrypted and classified automatically.
          </span>
        </div>
      </div>

      <DropzoneUpload
        onUploaded={() => {
          reload(1);
          refresh();
          reloadShared();
        }}
        folders={folders}
        currentFolderId={uploadFolderId}
        onFolderChange={setUploadFolderId}
      />

      <div className="tabs">
        <button
          className={tab === "mine" ? "tab active" : "tab"}
          onClick={() => setTab("mine")}
        >
          My files ({total})
        </button>
        <button
          className={tab === "shared" ? "tab active" : "tab"}
          onClick={() => setTab("shared")}
        >
          Shared with me ({sharedFiles.length})
        </button>
      </div>

      {tab === "mine" && (
        <>
          {loading && <p className="text-muted">Loading files…</p>}
          {error && <p className="field-error">{error}</p>}
          {!loading && !error && (
            <FileTable
              files={files}
              page={page}
              perPage={PER_PAGE}
              total={total}
              onPageChange={(p) => reload(p)}
              onDeleted={() => {
                reload(page);
                refresh();
              }}
            />
          )}
        </>
      )}

      {tab === "shared" && (
        <>
          {sharedFiles.length === 0 ? (
            <div className="empty">
              <div className="empty-title">Nothing shared with you yet</div>
              <div className="text-small text-muted">
                When someone shares a file or folder with you, it'll show up here.
              </div>
            </div>
          ) : (
            <FileTable
              files={sharedFiles}
              page={1}
              perPage={sharedFiles.length}
              total={sharedFiles.length}
              onPageChange={() => {
                /* No pagination on the shared panel */
              }}
              showShare={false}
              showDelete={false}
            />
          )}
        </>
      )}
    </div>
  );
}
