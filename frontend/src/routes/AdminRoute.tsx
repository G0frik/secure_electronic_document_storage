import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/state/auth";

interface Props {
  children: ReactNode;
}

/**
 * Wraps a route in two gates: ProtectedRoute (must be logged in) implicitly
 * via the user check, plus an admin role guard. Non-admin users get sent home.
 */
export default function AdminRoute({ children }: Props) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <p className="status-pending">Loading…</p>;
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
