import { useCallback, useEffect, useRef, useState } from "react";
import {
  AppNotification,
  listNotifications,
  markAllRead,
  markRead,
  unreadCount,
} from "@/api/notifications";

const POLL_MS = 15_000;

function severityStyle(sev: AppNotification["severity"]): React.CSSProperties {
  if (sev === "critical")
    return { background: "#fff0f0", borderLeft: "3px solid #d1242f" };
  if (sev === "warning")
    return { background: "#fff8c5", borderLeft: "3px solid #bf8700" };
  return { background: "white", borderLeft: "3px solid #d0d7de" };
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setCount(await unreadCount());
    } catch (err) {
      // Anonymous + half-authenticated routes get 401 here; just ignore.
      console.debug("unread count fetch skipped", err);
    }
  }, []);

  const loadList = useCallback(async () => {
    try {
      const data = await listNotifications({ limit: 30 });
      setItems(data.items);
      setCount(data.unread_count);
    } catch (err) {
      console.warn("notifications fetch failed", err);
    }
  }, []);

  useEffect(() => {
    refreshCount();
    const id = window.setInterval(refreshCount, POLL_MS);
    return () => window.clearInterval(id);
  }, [refreshCount]);

  // When dropdown opens, fetch the full list.
  useEffect(() => {
    if (open) loadList();
  }, [open, loadList]);

  // Click-outside to close.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  async function onMarkRead(id: string) {
    try {
      await markRead(id);
      await loadList();
    } catch (err) {
      console.warn("mark read failed", err);
    }
  }

  async function onMarkAll() {
    try {
      await markAllRead();
      await loadList();
    } catch (err) {
      console.warn("mark all failed", err);
    }
  }

  return (
    <div ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Notifications"
        style={{ padding: "0.2em 0.5em" }}
      >
        Bell {count > 0 && (
          <span
            style={{
              marginLeft: "0.25rem",
              padding: "0.05em 0.4em",
              background: "#d1242f",
              color: "white",
              borderRadius: "8px",
              fontSize: "0.75em",
              fontWeight: "bold",
            }}
          >
            {count}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: "0.5rem",
            width: "24rem",
            maxHeight: "32rem",
            overflowY: "auto",
            background: "white",
            border: "1px solid #d0d7de",
            borderRadius: "6px",
            boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
            zIndex: 999,
            textAlign: "left",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "0.5rem 0.75rem",
              borderBottom: "1px solid #eaeef2",
            }}
          >
            <strong>Notifications</strong>
            <button type="button" onClick={onMarkAll} disabled={count === 0}>
              Mark all read
            </button>
          </div>

          {items.length === 0 && (
            <p style={{ padding: "1rem", color: "#6e7781", margin: 0 }}>
              No notifications yet.
            </p>
          )}

          {items.map((n) => (
            <div
              key={n.id}
              style={{
                padding: "0.6rem 0.75rem",
                borderBottom: "1px solid #eaeef2",
                opacity: n.read_at ? 0.6 : 1,
                ...severityStyle(n.severity),
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                <strong>{n.title}</strong>
                {!n.read_at && (
                  <button
                    type="button"
                    onClick={() => onMarkRead(n.id)}
                    style={{ fontSize: "0.75em" }}
                    title="Mark read"
                  >
                    ✓
                  </button>
                )}
              </div>
              {n.body && (
                <p style={{ margin: "0.25rem 0 0", fontSize: "0.85em", color: "#6e7781" }}>
                  {n.body}
                </p>
              )}
              <p style={{ margin: "0.25rem 0 0", fontSize: "0.75em", color: "#a0a8b0" }}>
                {n.action_type} · {new Date(n.created_at).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
