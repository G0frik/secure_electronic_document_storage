import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { fetchHealth } from "@/api/health";
import { listFiles, listSharedFiles, StoredFile } from "@/api/files";
import { Folder, listFolders } from "@/api/folders";
import { useAuth } from "@/state/auth";
import FileTable from "@/components/FileTable";
import UploadForm from "@/components/UploadForm";

const PER_PAGE = 50;

export default function HomePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [files, setFiles] = useState<StoredFile[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchHealth()
      .then(() => setHealthOk(true))
      .catch(() => setHealthOk(false));
  }, []);

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <main>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          borderBottom: "1px solid #eaeef2",
          paddingBottom: "0.75rem",
          marginBottom: "1.25rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Secure Document Storage</h1>
        {user && (
          <small style={{ color: "#6e7781" }}>
            {user.email} ({user.role}
            {user.department ? ` · ${user.department}` : ""}){" "}
            {user.two_factor_enabled && (
              <span
                title="Two-factor authentication enabled"
                style={{
                  marginLeft: "0.25rem",
                  fontSize: "0.75em",
                  padding: "0.1em 0.4em",
                  border: "1px solid #1f883d",
                  borderRadius: "3px",
                  color: "#1f883d",
                }}
              >
                2FA
              </span>
            )}
            <Link to="/folders" style={{ marginLeft: "0.5rem" }}>
              Folders
            </Link>{" "}
            <Link to="/trash" style={{ marginLeft: "0.25rem" }}>
              Trash
            </Link>{" "}
            <Link to="/settings/security" style={{ marginLeft: "0.25rem" }}>
              Security
            </Link>{" "}
            <button onClick={onLogout} style={{ marginLeft: "0.25rem" }}>
              Logout
            </button>
          </small>
        )}
      </header>

      <UploadForm
        onUploaded={() => reload(1)}
        folders={folders}
        currentFolderId={uploadFolderId}
        onFolderChange={setUploadFolderId}
      />

      <h2 style={{ marginBottom: "0.5rem" }}>My files</h2>
      {loading && <p className="status-pending">Loading files…</p>}
      {error && <p className="status-fail">{error}</p>}
      {!loading && !error && (
        <FileTable
          files={files}
          page={page}
          perPage={PER_PAGE}
          total={total}
          onPageChange={(p) => reload(p)}
          onDeleted={() => reload(page)}
        />
      )}

      <h2 style={{ marginTop: "2rem", marginBottom: "0.5rem" }}>
        Shared with me ({sharedFiles.length})
      </h2>
      {sharedFiles.length === 0 ? (
        <p className="status-pending">Nothing shared with you yet.</p>
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

      <footer style={{ marginTop: "2rem", color: "#6e7781", fontSize: "0.85em" }}>
        Backend health:{" "}
        {healthOk === null && <span className="status-pending">checking…</span>}
        {healthOk === true && <span className="status-ok">ok</span>}
        {healthOk === false && <span className="status-fail">unreachable</span>}
      </footer>
    </main>
  );
}
