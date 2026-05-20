import { Route, Routes } from "react-router-dom";
import FoldersPage from "@/pages/FoldersPage";
import HomePage from "@/pages/HomePage";
import LoginPage from "@/pages/LoginPage";
import SecuritySettingsPage from "@/pages/SecuritySettingsPage";
import ProtectedRoute from "@/routes/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
        path="/settings/security"
        element={
          <ProtectedRoute>
            <SecuritySettingsPage />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
