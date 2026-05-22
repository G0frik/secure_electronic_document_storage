import { useCallback, useEffect, useRef, useState } from "react";
import {
  AppNotification,
  listNotifications,
  markAllRead,
  markRead,
  unreadCount,
} from "@/api/notifications";
import { Bell, CheckCircle2 } from "@/components/icons";

const POLL_MS = 15_000;

function rowClassFor(read: boolean): string {
  // The .notification-row.unread state gives the soft accent tint; severity
  // border lives on a left-border style inline at the call site.
  return read ? "notification-row" : "notification-row unread";
}

function severityBorder(sev: AppNotification["severity"]): string {
  if (sev === "critical") return "var(--color-danger)";
  if (sev === "warning") return "var(--color-warning)";
  return "var(--color-line-strong)";
}

/**
 * Topbar notification bell.
 *
 * Polls `/api/notifications/unread-count` every 15s for the badge.
 * Opens a popover panel showing the 30 most recent notifications with
 * a per-row mark-as-read and a bulk mark-all-read.
 */
export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setCount(await unreadCount());
    } catch (err) {
      // Anonymous / pending-TOTP sessions return 401 here; ignore.
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

  useEffect(() => {
    if (open) loadList();
  }, [open, loadList]);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
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
    <div ref={wrapperRef} className="notification-bell" style={{ position: "relative" }}>
      <button
        type="button"
        className="btn btn-ghost btn-icon"
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications"
        title="Notifications"
      >
        <Bell size={18} />
        {count > 0 && <span className="notification-badge">{count}</span>}
      </button>

      {open && (
        <div
          className="popover notification-list"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 999,
            textAlign: "left",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "var(--space-3) var(--space-4)",
              borderBottom: "1px solid var(--color-line)",
            }}
          >
            <strong style={{ fontSize: "0.875rem" }}>Notifications</strong>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onMarkAll}
              disabled={count === 0}
            >
              Mark all read
            </button>
          </div>

          {items.length === 0 && (
            <p
              style={{
                padding: "var(--space-4)",
                color: "var(--color-muted)",
                margin: 0,
                fontSize: "0.875rem",
              }}
            >
              No notifications yet.
            </p>
          )}

          {items.map((n) => (
            <div
              key={n.id}
              className={rowClassFor(!!n.read_at)}
              style={{ borderLeft: `3px solid ${severityBorder(n.severity)}` }}
            >
              <div className="row row-between" style={{ gap: "var(--space-2)" }}>
                <span className="text-strong">{n.title}</span>
                {!n.read_at && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon btn-sm"
                    onClick={() => onMarkRead(n.id)}
                    aria-label="Mark read"
                    title="Mark read"
                  >
                    <CheckCircle2 size={14} />
                  </button>
                )}
              </div>
              {n.body && (
                <p
                  style={{
                    margin: "var(--space-1) 0 0",
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                  }}
                >
                  {n.body}
                </p>
              )}
              <p className="notification-meta">
                <span className="text-mono">{n.action_type}</span>
                <span>·</span>
                <span>{new Date(n.created_at).toLocaleString()}</span>
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
