import { FormEvent, useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  AdminDepartment,
  createDepartment,
  deleteDepartment,
  listDepartments,
  renameDepartment,
} from "@/api/admin";
import AdminShell from "@/components/AdminShell";

export default function AdminDepartmentsPage() {
  const [items, setItems] = useState<AdminDepartment[]>([]);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await listDepartments());
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load departments.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createDepartment(newName.trim());
      setNewName("");
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Create failed.");
    }
  }

  async function onRename(d: AdminDepartment) {
    const next = window.prompt(`Rename "${d.name}" to:`, d.name);
    if (!next || next === d.name) return;
    try {
      await renameDepartment(d.id, next);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Rename failed.");
    }
  }

  async function onDelete(d: AdminDepartment) {
    if (!window.confirm(`Delete department "${d.name}"?`)) return;
    try {
      await deleteDepartment(d.id);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Delete failed.");
    }
  }

  return (
    <AdminShell>
      <h1>Departments</h1>
      {error && <p className="status-fail">{error}</p>}

      <form onSubmit={onCreate} style={{ display: "flex", gap: "0.5rem", margin: "1rem 0" }}>
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New department name"
          style={{ padding: "0.4rem", flex: 1, maxWidth: "20rem" }}
          required
        />
        <button type="submit" disabled={!newName.trim()}>
          Create
        </button>
      </form>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.4rem" }}>Name</th>
            <th style={{ padding: "0.4rem" }}>Created</th>
            <th style={{ padding: "0.4rem" }}></th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.4rem" }}>{d.name}</td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {new Date(d.created_at).toLocaleString()}
              </td>
              <td style={{ padding: "0.4rem" }}>
                <button onClick={() => onRename(d)}>Rename</button>{" "}
                <button onClick={() => onDelete(d)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </AdminShell>
  );
}
