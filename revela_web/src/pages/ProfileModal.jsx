import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function ProfileModal({ onClose }) {
  const { user } = useAuth();
  const navigate = useNavigate();

  const handleManageSecurity = () => {
    if (onClose) onClose();
    navigate("/settings");
  };

  const fullName = user?.fullName || "Unknown User";
  const email = user?.email || "No email provided";
  const role = user?.role || "Administrator";
  const initials = user?.fullName 
    ? user.fullName.split(" ").map(n => n[0]).join("").substring(0, 2).toUpperCase() 
    : "?";

  return (
    <div className="modal-backdrop" style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }} onClick={onClose}>
      <div className="modal-panel saas-card frosted-glass" style={{ width: "min(100%, 500px)", display: "flex", flexDirection: "column", gap: 24, position: "relative", padding: 32, background: "var(--color-modal-bg)", boxShadow: "0 24px 60px rgba(15,23,42,0.18)" }} onClick={e => e.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose} style={{ position: "absolute", top: 16, right: 16 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
        
        <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
          <div style={{ width: 80, height: 80, borderRadius: "50%", background: "var(--color-primary)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 28, fontWeight: 700, boxShadow: "0 8px 16px rgba(86, 171, 47, 0.2)", flexShrink: 0 }}>
            {initials}
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 22, color: "var(--color-ink)" }}>{fullName}</h2>
            <p style={{ margin: "4px 0 0", color: "var(--color-muted)", fontSize: 14 }}>{role}</p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px 16px", borderTop: "1px solid var(--color-border-soft)", paddingTop: 20 }}>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "var(--color-muted)", fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Email Address</label>
            <div style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 500 }}>{email}</div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "var(--color-muted)", fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Office / Department</label>
            <div style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 500 }}>{user?.office || "Mataasnakahoy BPLO"}</div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "var(--color-muted)", fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Account Status</label>
            <div><span className="badge badge--green">Active</span></div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "var(--color-muted)", fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Last Sign In</label>
            <div style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 500 }}>{user?.lastLogin || "Just now"}</div>
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--color-border-soft)", paddingTop: 24, display: "flex", justifyContent: "flex-end", gap: 12 }}>
          <button className="ghost-btn" onClick={onClose}>Close</button>
          <button className="primary-btn" onClick={handleManageSecurity}>Manage Security</button>
        </div>
      </div>
    </div>
  );
}
