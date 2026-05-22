import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/state/auth";
import NotificationBell from "@/components/NotificationBell";
import { ChevronDown, Lock, LogOut, Search, Settings, ShieldCheck } from "@/components/icons";

/**
 * Top navigation bar for the authenticated app shell.
 *
 * Layout: brand on the left → disabled search stub (search isn't a
 * shipped feature yet) → notification bell + account menu on the right.
 * Pulls user info from the auth context; the account menu reveals the
 * email + role and houses the Security / Admin / Logout actions.
 */
export default function TopBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "·";
  const isAdmin = user?.role === "admin";

  return (
    <header className="topbar" role="banner">
      <div className="topbar-brand">
        <span className="topbar-brand-mark" aria-hidden="true">
          <Lock size={14} strokeWidth={2.5} />
        </span>
        <span>Secure Docs</span>
      </div>

      {/* Search is a placeholder — not a shipped feature yet. Disabled so it
          reads as "coming" rather than broken. */}
      <div className="topbar-search" aria-disabled="true" title="Search is not available yet">
        <Search size={14} />
        <span>Search…</span>
      </div>

      <div className="topbar-spacer" />

      <div className="topbar-actions">
        <NotificationBell />

        {user && (
          <div ref={menuRef} style={{ position: "relative" }}>
            <button
              type="button"
              className="topbar-account"
              onClick={() => setMenuOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <span className="topbar-account-avatar">{initials}</span>
              <span className="text-small">{user.email}</span>
              <ChevronDown size={14} />
            </button>

            {menuOpen && (
              <div
                className="popover"
                role="menu"
                style={{
                  position: "absolute",
                  top: "calc(100% + 6px)",
                  right: 0,
                  minWidth: 220,
                  zIndex: 999,
                  padding: "var(--space-2) 0",
                }}
              >
                <div
                  style={{
                    padding: "var(--space-2) var(--space-4)",
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                  }}
                >
                  Signed in as
                  <div className="text-mono" style={{ color: "var(--color-ink)" }}>
                    {user.email}
                  </div>
                  <div className="text-mono text-small text-muted">
                    {user.role}
                    {user.department ? ` · ${user.department}` : ""}
                  </div>
                </div>
                <div className="divider" style={{ margin: "var(--space-2) 0" }} />
                <MenuItem
                  icon={<Settings size={14} />}
                  label="Security settings"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate("/settings/security");
                  }}
                />
                {isAdmin && (
                  <MenuItem
                    icon={<ShieldCheck size={14} />}
                    label="Admin"
                    onClick={() => {
                      setMenuOpen(false);
                      navigate("/admin");
                    }}
                  />
                )}
                <MenuItem
                  icon={<LogOut size={14} />}
                  label="Log out"
                  onClick={async () => {
                    setMenuOpen(false);
                    await logout();
                    navigate("/login");
                  }}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        width: "100%",
        padding: "var(--space-2) var(--space-4)",
        background: "transparent",
        border: "none",
        textAlign: "left",
        font: "inherit",
        color: "var(--color-ink)",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-bg)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {icon}
      {label}
    </button>
  );
}
