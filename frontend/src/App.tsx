import { Route, Routes } from "react-router-dom";
import AdminTierOverridesPage from "@/pages/AdminTierOverridesPage";
import FoldersPage from "@/pages/FoldersPage";
import HomePage from "@/pages/HomePage";
import LoginPage from "@/pages/LoginPage";
import PublicSharePage from "@/pages/PublicSharePage";
import SecuritySettingsPage from "@/pages/SecuritySettingsPage";
import TrashPage from "@/pages/TrashPage";
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
        path="/admin/overrides"
        element={
          <ProtectedRoute>
            <AdminTierOverridesPage />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
