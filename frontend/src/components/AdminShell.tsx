import { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/state/auth";

interface Props {
  children: ReactNode;
}

const NAV = [
  { to: "/admin", label: "Overview", end: true },
  { to: "/admin/users", label: "Users" },
  { to: "/admin/departments", label: "Departments" },
  { to: "/admin/groups", label: "Groups" },
  { to: "/admin/policies", label: "Policies" },
  { to: "/admin/overrides", label: "Tier overrides" },
  { to: "/admin/events", label: "Events / SIEM" },
];

/**
 * Legacy admin layout. Kept as-is during the user-facing redesign batch
 * to avoid blowing up scope. The "Legacy admin UI" banner makes the
 * inconsistency intentional rather than embarrassing.
 *
 * Renders inside AppShell now, so its outer wrapper is a `<section>` (not
 * `<main>` — AppShell owns that) and it doesn't duplicate the topbar.
 */
export default function AdminShell({ children }: Props) {
  const { user } = useAuth();
  const navigate = useNavigate();
  return (
    <section className="page" style={{ maxWidth: "100%" }}>
      <div className="legacy-banner">
        Legacy admin UI — pending redesign. The user-facing pages have moved to
        the Paper Archive design; admin pages follow in a later batch.
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "12rem 1fr",
          gap: "1.5rem",
        }}
      >
        <nav
          style={{
            borderRight: "1px solid #eaeef2",
            paddingRight: "1rem",
            minHeight: "60vh",
          }}
        >
          <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1em" }}>Admin</h2>
          <p
            style={{
              fontSize: "0.8em",
              color: "#6e7781",
              margin: "0 0 0.75rem",
            }}
          >
            Signed in as {user?.email}
          </p>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {NAV.map((n) => (
              <li key={n.to} style={{ margin: "0.2rem 0" }}>
                <NavLink
                  to={n.to}
                  end={n.end}
                  style={({ isActive }) => ({
                    display: "block",
                    padding: "0.25rem 0.5rem",
                    borderRadius: "3px",
                    textDecoration: "none",
                    background: isActive ? "#dbeafe" : "transparent",
                    color: isActive ? "#0969da" : "#24292f",
                    fontWeight: isActive ? "bold" : "normal",
                  })}
                >
                  {n.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <p style={{ marginTop: "1.5rem" }}>
            <Link to="/">← Back to files</Link>
          </p>
          <p style={{ marginTop: "0.5rem", fontSize: "0.75em", color: "#6e7781" }}>
            <button onClick={() => navigate(-1)}>Back</button>
          </p>
        </nav>
        <section>{children}</section>
      </div>
    </section>
  );
}
