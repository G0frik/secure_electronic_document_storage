import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  AdminDepartment,
  AdminUser,
  forceLogout,
  listDepartments,
  listUsers,
  updateUser,
  userAudit,
  AuditRow,
} from "@/api/admin";
import { Role, UserStatus } from "@/api/auth";
import AdminShell from "@/components/AdminShell";
import { formatBytes, formatDateTime } from "@/utils/format";

const ROLES: Role[] = ["admin", "user", "guest"];
const STATUSES: UserStatus[] = ["active", "disabled", "locked"];

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [departments, setDepartments] = useState<AdminDepartment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [auditFor, setAuditFor] = useState<AdminUser | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [u, d] = await Promise.all([listUsers(), listDepartments()]);
      setUsers(u);
      setDepartments(d);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load users.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function applyEdit(patch: Parameters<typeof updateUser>[1]) {
    if (!editing) return;
    try {
      await updateUser(editing.id, patch);
      setEditing(null);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Update failed.");
    }
  }

  async function onForceLogout(u: AdminUser) {
    if (!window.confirm(`Force logout for ${u.email}?`)) return;
    try {
      await forceLogout(u.id);
      await refresh();
    } catch (err) {
      console.error(err);
      alert("Force logout failed — see console.");
    }
  }

  async function openAudit(u: AdminUser) {
    setAuditFor(u);
    try {
      setAudit(await userAudit(u.id, 100));
    } catch (err) {
      console.error(err);
      setAudit([]);
    }
  }

  return (
    <AdminShell>
      <h1>Users</h1>
      {error && <p className="status-fail">{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.4rem" }}>Email</th>
            <th style={{ padding: "0.4rem" }}>Role</th>
            <th style={{ padding: "0.4rem" }}>Status</th>
            <th style={{ padding: "0.4rem" }}>Department</th>
            <th style={{ padding: "0.4rem" }}>Quota</th>
            <th style={{ padding: "0.4rem" }}>Last login</th>
            <th style={{ padding: "0.4rem" }}></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.4rem" }}>{u.email}</td>
              <td style={{ padding: "0.4rem" }}>{u.role}</td>
              <td style={{ padding: "0.4rem" }}>
                <span
                  className={
                    u.status === "active"
                      ? "status-ok"
                      : u.status === "disabled"
                        ? "status-fail"
                        : "status-pending"
                  }
                >
                  {u.status}
                </span>
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>{u.department ?? "—"}</td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {formatBytes(u.used_bytes)} / {formatBytes(u.quota_bytes)}
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {u.last_login_at ? formatDateTime(u.last_login_at) : "—"}
              </td>
              <td style={{ padding: "0.4rem" }}>
                <button onClick={() => setEditing(u)}>Edit</button>{" "}
                <button onClick={() => onForceLogout(u)}>Force logout</button>{" "}
                <button onClick={() => openAudit(u)}>Audit</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <EditModal
          user={editing}
          departments={departments}
          onClose={() => setEditing(null)}
          onSave={applyEdit}
        />
      )}

      {auditFor && (
        <AuditModal
          user={auditFor}
          items={audit}
          onClose={() => {
            setAuditFor(null);
            setAudit([]);
          }}
        />
      )}
    </AdminShell>
  );
}

function EditModal({
  user,
  departments,
  onClose,
  onSave,
}: {
  user: AdminUser;
  departments: AdminDepartment[];
  onClose: () => void;
  onSave: (body: Parameters<typeof updateUser>[1]) => void;
}) {
  const [role, setRole] = useState<Role>(user.role);
  const [status, setStatus] = useState<UserStatus>(user.status);
  const [departmentId, setDepartmentId] = useState<string>(user.department_id ?? "");
  const [quotaMb, setQuotaMb] = useState<number>(Math.round(user.quota_bytes / (1024 * 1024)));

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white",
          padding: "1.5rem",
          minWidth: "28rem",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>Edit {user.email}</h3>
        <p>
          Role:&nbsp;
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </p>
        <p>
          Status:&nbsp;
          <select value={status} onChange={(e) => setStatus(e.target.value as UserStatus)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </p>
        <p>
          Department:&nbsp;
          <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
            <option value="">— none —</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </p>
        <p>
          Quota (MB):&nbsp;
          <input
            type="number"
            min={0}
            value={quotaMb}
            onChange={(e) => setQuotaMb(Number(e.target.value))}
            style={{ width: "8rem" }}
          />
        </p>
        <p style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <button onClick={onClose}>Cancel</button>
          <button
            onClick={() => {
              const body: Parameters<typeof updateUser>[1] = {
                role,
                status,
                quota_bytes: quotaMb * 1024 * 1024,
              };
              if (departmentId) {
                body.department_id = departmentId;
              } else {
                body.clear_department = true;
              }
              onSave(body);
            }}
          >
            Save
          </button>
        </p>
      </div>
    </div>
  );
}

function AuditModal({
  user,
  items,
  onClose,
}: {
  user: AdminUser;
  items: AuditRow[];
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white",
          padding: "1.5rem",
          minWidth: "42rem",
          maxHeight: "80vh",
          overflowY: "auto",
          border: "1px solid #d0d7de",
          borderRadius: "6px",
        }}
      >
        <h3 style={{ marginTop: 0 }}>Audit for {user.email}</h3>
        {items.length === 0 ? (
          <p className="status-pending">No audit rows for this user.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #d0d7de" }}>
                <th style={{ padding: "0.3rem" }}>When</th>
                <th style={{ padding: "0.3rem" }}>Action</th>
                <th style={{ padding: "0.3rem" }}>Severity</th>
                <th style={{ padding: "0.3rem" }}>Target</th>
                <th style={{ padding: "0.3rem" }}>IP</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid #eaeef2" }}>
                  <td style={{ padding: "0.3rem", color: "#6e7781" }}>
                    {new Date(r.timestamp).toLocaleString()}
                  </td>
                  <td style={{ padding: "0.3rem" }}>
                    <code>{r.action_type}</code>
                  </td>
                  <td style={{ padding: "0.3rem" }}>{r.severity}</td>
                  <td style={{ padding: "0.3rem", color: "#6e7781" }}>{r.target_type ?? "—"}</td>
                  <td style={{ padding: "0.3rem", color: "#6e7781" }}>{r.actor_ip ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p style={{ display: "flex", justifyContent: "flex-end", marginTop: "1rem" }}>
          <button onClick={onClose}>Close</button>
        </p>
      </div>
    </div>
  );
}
