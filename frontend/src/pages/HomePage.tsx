import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { fetchHealth } from "@/api/health";
import { listFiles, StoredFile } from "@/api/files";
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

  const reload = useCallback(
    async (targetPage = page) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listFiles(targetPage, PER_PAGE);
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

  useEffect(() => {
    reload(1);
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
            <button onClick={onLogout} style={{ marginLeft: "0.5rem" }}>
              Logout
            </button>
          </small>
        )}
      </header>

      <UploadForm onUploaded={() => reload(1)} />

      {loading && <p className="status-pending">Loading files…</p>}
      {error && <p className="status-fail">{error}</p>}
      {!loading && !error && (
        <FileTable
          files={files}
          page={page}
          perPage={PER_PAGE}
          total={total}
          onPageChange={(p) => reload(p)}
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
