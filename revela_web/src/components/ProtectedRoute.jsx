import { useEffect } from "react";
import { useAuth } from "../context/authContext";
import { Navigate } from "react-router-dom";
import RevelaLoader from "./RevelaLoader";

const ALLOWED_ROLES = ["Admin", "SUPER_ADMIN", "System Administrator"];

export default function ProtectedRoute({ children }) {
  const { token, user, logout, signingOut } = useAuth();

  // If user is loaded and their role is forbidden, clear the session
  const isForbidden = user && !ALLOWED_ROLES.includes(user.role);

  useEffect(() => {
    if (isForbidden) logout();
  }, [isForbidden, logout]);

  // Not logged in at all → back to login
  if (signingOut) return null;
  if (!token) return <Navigate to="/login" replace />;

  // Token exists but user profile hasn't loaded yet → wait
  if (!user) {
    return <RevelaLoader message="Verifying access…" />;
  }

  // Logged in but role is not permitted to use the web dashboard
  if (isForbidden) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
