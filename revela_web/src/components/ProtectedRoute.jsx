import { useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { Navigate } from "react-router-dom";

const ALLOWED_ROLES = ["Admin", "SUPER_ADMIN", "System Administrator"];

export default function ProtectedRoute({ children }) {
  const { token, user, logout } = useAuth();

  // If user is loaded and their role is forbidden, clear the session
  const isForbidden = user && !ALLOWED_ROLES.includes(user.role);

  useEffect(() => {
    if (isForbidden) logout();
  }, [isForbidden]);

  // Not logged in at all → back to login
  if (!token) return <Navigate to="/" replace />;

  // Token exists but user profile hasn't loaded yet → wait
  if (!user) {
    return (
      <div style={{
        position: 'fixed', inset: 0,
        backgroundColor: 'var(--color-bg)',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        zIndex: 9999,
        transition: 'background-color 0.3s ease'
      }}>
        
        <img 
          src="/searching.png" 
          alt="Revela Mascot Peaking" 
          style={{
            height: '240px',
            width: 'auto',
            objectFit: 'contain',
            WebkitMaskImage: 'linear-gradient(to bottom, rgba(0,0,0,1) 80%, rgba(0,0,0,0) 100%)',
            maskImage: 'linear-gradient(to bottom, rgba(0,0,0,1) 80%, rgba(0,0,0,0) 100%)',
            marginBottom: '24px'
          }} 
        />
        
        <div style={{
           display: 'flex',
           flexDirection: 'column',
           alignItems: 'center',
           gap: '16px',
        }}>
          <div style={{
            width: '36px', height: '36px',
            border: '4px solid var(--color-border)',
            borderTopColor: 'var(--color-primary)',
            borderRadius: '50%',
            animation: 'spin 1s ease-in-out infinite'
          }}></div>
          <h2 style={{ color: 'var(--color-ink)', fontWeight: '700', letterSpacing: '-0.3px', fontSize: '18px', margin: 0 }}>
            Verifying Access...
          </h2>
        </div>
      </div>
    );
  }

  // Logged in but role is not permitted to use the web dashboard
  if (isForbidden) {
    return <Navigate to="/" replace />;
  }

  return children;
}