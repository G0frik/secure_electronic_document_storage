import { Route, Routes } from "react-router-dom";
import AdminTierOverridesPage from "@/pages/AdminTierOverridesPage";
import AdminDepartmentsPage from "@/pages/admin/AdminDepartmentsPage";
import AdminEventsPage from "@/pages/admin/AdminEventsPage";
import AdminGroupsPage from "@/pages/admin/AdminGroupsPage";
import AdminHomePage from "@/pages/admin/AdminHomePage";
import AdminPoliciesPage from "@/pages/admin/AdminPoliciesPage";
import AdminUsersPage from "@/pages/admin/AdminUsersPage";
import FoldersPage from "@/pages/FoldersPage";
import HomePage from "@/pages/HomePage";
import LoginPage from "@/pages/LoginPage";
import PublicSharePage from "@/pages/PublicSharePage";
import SecuritySettingsPage from "@/pages/SecuritySettingsPage";
import TrashPage from "@/pages/TrashPage";
import AppShell from "@/components/AppShell";
import AdminRoute from "@/routes/AdminRoute";
import ProtectedRoute from "@/routes/ProtectedRoute";

/**
 * Route table.
 *
 * Public routes (`/login`, `/share/:token`) render directly — they have
 * their own centered-card layouts. Every other route wraps the page in
 * `<AppShell>` (topbar + sidebar + main).
 */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/share/:token" element={<PublicSharePage />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell>
              <HomePage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/folders"
        element={
          <ProtectedRoute>
            <AppShell>
              <FoldersPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/trash"
        element={
          <ProtectedRoute>
            <AppShell>
              <TrashPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/security"
        element={
          <ProtectedRoute>
            <AppShell>
              <SecuritySettingsPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      {/* Admin pages still render inside AppShell (consistent topbar/sidebar),
          but they keep using AdminShell internally for the legacy admin nav
          until the deferred admin redesign batch lands. */}
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <AppShell>
              <AdminHomePage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/users"
        element={
          <AdminRoute>
            <AppShell>
              <AdminUsersPage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/departments"
        element={
          <AdminRoute>
            <AppShell>
              <AdminDepartmentsPage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/groups"
        element={
          <AdminRoute>
            <AppShell>
              <AdminGroupsPage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/policies"
        element={
          <AdminRoute>
            <AppShell>
              <AdminPoliciesPage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/overrides"
        element={
          <AdminRoute>
            <AppShell>
              <AdminTierOverridesPage />
            </AppShell>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/events"
        element={
          <AdminRoute>
            <AppShell>
              <AdminEventsPage />
            </AppShell>
          </AdminRoute>
        }
      />
    </Routes>
  );
}
