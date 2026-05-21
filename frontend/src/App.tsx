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
import AdminRoute from "@/routes/AdminRoute";
import ProtectedRoute from "@/routes/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/share/:token" element={<PublicSharePage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <HomePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/folders"
        element={
          <ProtectedRoute>
            <FoldersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/trash"
        element={
          <ProtectedRoute>
            <TrashPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/security"
        element={
          <ProtectedRoute>
            <SecuritySettingsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <AdminHomePage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/users"
        element={
          <AdminRoute>
            <AdminUsersPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/departments"
        element={
          <AdminRoute>
            <AdminDepartmentsPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/groups"
        element={
          <AdminRoute>
            <AdminGroupsPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/policies"
        element={
          <AdminRoute>
            <AdminPoliciesPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/overrides"
        element={
          <AdminRoute>
            <AdminTierOverridesPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/events"
        element={
          <AdminRoute>
            <AdminEventsPage />
          </AdminRoute>
        }
      />
    </Routes>
  );
}
