import { NavLink } from "react-router-dom";
import { useAuth } from "@/state/auth";
import QuotaBar from "@/components/QuotaBar";
import {
  Files,
  ShieldCheck,
  Trash2,
  Lock,
  HardDrive,
} from "@/components/icons";

/**
 * Left navigation for the authenticated app shell.
 *
 * Sections: primary navigation (file views), then security, then admin
 * (role-gated), then storage quota pinned at the bottom.
 *
 * The active-route highlight relies on NavLink's `isActive` flag — see
 * `.sidebar-item.active` in app.css for the styling.
 */
export default function Sidebar() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <nav className="sidebar" aria-label="Primary">
      <div className="sidebar-section">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            isActive ? "sidebar-item active" : "sidebar-item"
          }
        >
          <Files size={16} />
          <span>My files</span>
        </NavLink>

        <NavLink
          to="/folders"
          className={({ isActive }) =>
            isActive ? "sidebar-item active" : "sidebar-item"
          }
        >
          <HardDrive size={16} />
          <span>Folders &amp; shares</span>
        </NavLink>

        <NavLink
          to="/trash"
          className={({ isActive }) =>
            isActive ? "sidebar-item active" : "sidebar-item"
          }
        >
          <Trash2 size={16} />
          <span>Trash</span>
        </NavLink>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-label">Account</div>
        <NavLink
          to="/settings/security"
          className={({ isActive }) =>
            isActive ? "sidebar-item active" : "sidebar-item"
          }
        >
          <Lock size={16} />
          <span>Security</span>
        </NavLink>

        {isAdmin && (
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              isActive ? "sidebar-item active" : "sidebar-item"
            }
          >
            <ShieldCheck size={16} />
            <span>Admin</span>
          </NavLink>
        )}
      </div>

      <div className="sidebar-spacer" />

      <div className="sidebar-footer">
        <QuotaBar />
      </div>
    </nav>
  );
}

