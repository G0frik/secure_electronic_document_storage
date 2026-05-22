import { FormEvent, useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  AdminDepartment,
  AdminPolicy,
  createPolicy,
  deletePolicy,
  listDepartments,
  listPolicies,
  Tier,
  updatePolicy,
} from "@/api/admin";
import { Role } from "@/api/auth";
import AdminShell from "@/components/AdminShell";

const ROLES: Role[] = ["admin", "user", "guest"];
const TIERS: Tier[] = ["public", "internal", "confidential", "restricted"];

export default function AdminPoliciesPage() {
  const [policies, setPolicies] = useState<AdminPolicy[]>([]);
  const [departments, setDepartments] = useState<AdminDepartment[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newRole, setNewRole] = useState<Role>("user");
  const [newDept, setNewDept] = useState<string>("");
  const [newTier, setNewTier] = useState<Tier>("confidential");
  const [newDeniedCategories, setNewDeniedCategories] = useState<string>("");
  const [newDescription, setNewDescription] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const [p, d] = await Promise.all([listPolicies(), listDepartments()]);
      setPolicies(p);
      setDepartments(d);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const denied = newDeniedCategories
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await createPolicy({
        role: newRole,
        department_id: newDept || null,
        allowed_max_tier: newTier,
        denied_categories: denied.length > 0 ? denied : null,
        description: newDescription.trim() || null,
      });
      setNewDept("");
      setNewDeniedCategories("");
      setNewDescription("");
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Create failed.");
    }
  }

  async function onChangeTier(p: AdminPolicy, tier: Tier) {
    try {
      await updatePolicy(p.id, { allowed_max_tier: tier });
      await refresh();
    } catch (err) {
      console.error(err);
    }
  }

  async function onDelete(p: AdminPolicy) {
    if (!window.confirm(`Delete policy ${p.role} / ${p.department ?? "global"}?`)) return;
    try {
      await deletePolicy(p.id);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Delete failed.");
    }
  }

  return (
    <AdminShell>
      <h1>Access policies</h1>
      <p style={{ color: "#6e7781" }}>
        Resolution order: <strong>group</strong> → <strong>department</strong> →{" "}
        <strong>global</strong>. Among group-targeted policies the max-permissive{" "}
        <code>allowed_max_tier</code> wins.
      </p>
      {error && <p className="status-fail">{error}</p>}

      <form
        onSubmit={onCreate}
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          margin: "1rem 0",
          padding: "0.75rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <strong>New:</strong>
        <select value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select value={newDept} onChange={(e) => setNewDept(e.target.value)}>
          <option value="">— global —</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              dept: {d.name}
            </option>
          ))}
        </select>
        <span>max tier:</span>
        <select value={newTier} onChange={(e) => setNewTier(e.target.value as Tier)}>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          value={newDeniedCategories}
          onChange={(e) => setNewDeniedCategories(e.target.value)}
          placeholder="denied categories (comma-separated)"
          style={{ flex: 1, padding: "0.4rem", minWidth: "20rem" }}
        />
        <input
          value={newDescription}
          onChange={(e) => setNewDescription(e.target.value)}
          placeholder="description"
          style={{ flex: 1, padding: "0.4rem", minWidth: "20rem" }}
        />
        <button type="submit">Create</button>
      </form>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.4rem" }}>Role</th>
            <th style={{ padding: "0.4rem" }}>Department</th>
            <th style={{ padding: "0.4rem" }}>Max tier</th>
            <th style={{ padding: "0.4rem" }}>Denied categories</th>
            <th style={{ padding: "0.4rem" }}>Description</th>
            <th style={{ padding: "0.4rem" }}></th>
          </tr>
        </thead>
        <tbody>
          {policies.map((p) => (
            <tr key={p.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.4rem" }}>{p.role}</td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {p.department ?? "— global —"}
              </td>
              <td style={{ padding: "0.4rem" }}>
                <select
                  value={p.allowed_max_tier}
                  onChange={(e) => onChangeTier(p, e.target.value as Tier)}
                >
                  {TIERS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {(p.denied_categories ?? []).join(", ") || "—"}
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>{p.description ?? "—"}</td>
              <td style={{ padding: "0.4rem" }}>
                <button onClick={() => onDelete(p)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </AdminShell>
  );
}
