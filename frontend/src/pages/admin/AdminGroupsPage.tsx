import { FormEvent, useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import {
  addGroupMember,
  AdminGroup,
  AdminUser,
  createGroup,
  deleteGroup,
  getGroup,
  listGroups,
  listUsers,
  removeGroupMember,
  updateGroup,
} from "@/api/admin";
import AdminShell from "@/components/AdminShell";

export default function AdminGroupsPage() {
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<AdminGroup | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [g, u] = await Promise.all([listGroups(), listUsers()]);
      setGroups(g);
      setUsers(u);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Failed to load groups.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function reopenGroup(id: string) {
    setOpenGroup(await getGroup(id));
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createGroup(newName.trim(), newDesc.trim() || null);
      setNewName("");
      setNewDesc("");
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      setError(ax.response?.data?.message ?? "Create failed.");
    }
  }

  async function onRename(g: AdminGroup) {
    const next = window.prompt(`Rename "${g.name}" to:`, g.name);
    if (!next || next === g.name) return;
    try {
      await updateGroup(g.id, { name: next });
      await refresh();
      if (openGroup?.id === g.id) await reopenGroup(g.id);
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Rename failed.");
    }
  }

  async function onDelete(g: AdminGroup) {
    if (!window.confirm(`Delete group "${g.name}" and all memberships?`)) return;
    try {
      await deleteGroup(g.id);
      if (openGroup?.id === g.id) setOpenGroup(null);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ message?: string }>;
      alert(ax.response?.data?.message ?? "Delete failed.");
    }
  }

  async function onAddMember(groupId: string, userId: string) {
    try {
      await addGroupMember(groupId, userId);
      await reopenGroup(groupId);
    } catch (err) {
      console.error(err);
    }
  }

  async function onRemoveMember(groupId: string, userId: string) {
    try {
      await removeGroupMember(groupId, userId);
      await reopenGroup(groupId);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <AdminShell>
      <h1>Groups</h1>
      {error && <p className="status-fail">{error}</p>}

      <form onSubmit={onCreate} style={{ display: "flex", gap: "0.5rem", margin: "1rem 0" }}>
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Group name"
          required
          style={{ padding: "0.4rem", width: "16rem" }}
        />
        <input
          value={newDesc}
          onChange={(e) => setNewDesc(e.target.value)}
          placeholder="Description (optional)"
          style={{ padding: "0.4rem", flex: 1, maxWidth: "30rem" }}
        />
        <button type="submit" disabled={!newName.trim()}>
          Create
        </button>
      </form>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #d0d7de" }}>
            <th style={{ padding: "0.4rem" }}>Name</th>
            <th style={{ padding: "0.4rem" }}>Description</th>
            <th style={{ padding: "0.4rem" }}>Created</th>
            <th style={{ padding: "0.4rem" }}></th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.id} style={{ borderBottom: "1px solid #eaeef2" }}>
              <td style={{ padding: "0.4rem" }}>{g.name}</td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {g.description ?? "—"}
              </td>
              <td style={{ padding: "0.4rem", color: "#6e7781" }}>
                {new Date(g.created_at).toLocaleString()}
              </td>
              <td style={{ padding: "0.4rem" }}>
                <button onClick={() => reopenGroup(g.id)}>Members…</button>{" "}
                <button onClick={() => onRename(g)}>Rename</button>{" "}
                <button onClick={() => onDelete(g)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {openGroup && (
        <MembersPanel
          group={openGroup}
          allUsers={users}
          onAdd={(uid) => onAddMember(openGroup.id, uid)}
          onRemove={(uid) => onRemoveMember(openGroup.id, uid)}
          onClose={() => setOpenGroup(null)}
        />
      )}
    </AdminShell>
  );
}

function MembersPanel({
  group,
  allUsers,
  onAdd,
  onRemove,
  onClose,
}: {
  group: AdminGroup;
  allUsers: AdminUser[];
  onAdd: (userId: string) => void;
  onRemove: (userId: string) => void;
  onClose: () => void;
}) {
  const memberIds = new Set((group.members ?? []).map((m) => m.id));
  const available = allUsers.filter((u) => !memberIds.has(u.id));
  return (
    <div
      style={{
        marginTop: "2rem",
        border: "1px solid #d0d7de",
        borderRadius: "6px",
        padding: "1rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Members of {group.name}</h2>
        <button onClick={onClose}>Close</button>
      </div>
      {(group.members ?? []).length === 0 ? (
        <p className="status-pending">No members yet.</p>
      ) : (
        <ul>
          {group.members?.map((m) => (
            <li key={m.id}>
              {m.email} ({m.role}){" "}
              <button onClick={() => onRemove(m.id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <h3 style={{ marginTop: "1rem" }}>Add member</h3>
      {available.length === 0 ? (
        <p style={{ color: "#6e7781" }}>Everyone is already in this group.</p>
      ) : (
        <select
          onChange={(e) => {
            if (e.target.value) {
              onAdd(e.target.value);
              e.target.value = "";
            }
          }}
          defaultValue=""
          style={{ padding: "0.4rem" }}
        >
          <option value="">— pick a user —</option>
          {available.map((u) => (
            <option key={u.id} value={u.id}>
              {u.email} ({u.role})
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
