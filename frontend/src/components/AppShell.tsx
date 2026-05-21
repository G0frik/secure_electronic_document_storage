import { ReactNode } from "react";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

/**
 * Authenticated app shell.
 *
 * Grid layout: top bar (56px) across the top, sidebar (240px) down the
 * left, main content fills the remaining area. Used by every protected
 * route (Home, Folders, Trash, Security, /admin/*).
 *
 * Public pages (login, public share landing) bypass the shell entirely
 * — they have their own centered-card layout.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <div className="app-topbar">
        <TopBar />
      </div>
      <div className="app-sidebar">
        <Sidebar />
      </div>
      <main className="app-main" role="main">
        {children}
      </main>
    </div>
  );
}
