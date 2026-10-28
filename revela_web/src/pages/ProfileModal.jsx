import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/authContext";

export default function ProfileModal({ onClose, onLogout, logoutPending = false }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);

  useEffect(() => {
    const previousFocus = document.activeElement;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll(
        'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [onClose]);

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
    <div className="modal-backdrop profile-modal-backdrop" onClick={onClose}>
      <div ref={dialogRef} className="modal-panel saas-card frosted-glass profile-modal"
        role="dialog" aria-modal="true" aria-labelledby="profile-modal-title"
        onClick={e => e.stopPropagation()}>
        <button ref={closeButtonRef} className="modal-close-btn profile-modal-close"
          type="button" onClick={onClose} aria-label="Close profile">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
        
        <div className="profile-modal-heading">
          <div className="profile-modal-avatar">
            {initials}
          </div>
          <div>
            <h2 id="profile-modal-title">{fullName}</h2>
            <p>{role}</p>
          </div>
        </div>

        <div className="profile-modal-details">
          <div>
            <label>Email Address</label>
            <div>{email}</div>
          </div>
          <div>
            <label>Office / Department</label>
            <div>{user?.office || "Mataasnakahoy BPLO"}</div>
          </div>
          <div>
            <label>Account Status</label>
            <div><span className="badge badge--green">Active</span></div>
          </div>
          <div>
            <label>Last Sign In</label>
            <div>{user?.lastLogin || "Just now"}</div>
          </div>
        </div>

        <div className="profile-modal-actions">
          <button className="profile-modal-logout" type="button" onClick={onLogout}
            disabled={logoutPending} aria-busy={logoutPending}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="m16 17 5-5-5-5M21 12H9" />
            </svg>
            {logoutPending ? "Signing out…" : "Logout"}
          </button>
          <div className="profile-modal-secondary-actions">
            <button className="ghost-btn" type="button" onClick={onClose}>Close</button>
            <button className="primary-btn" type="button" onClick={handleManageSecurity}>Manage Security</button>
          </div>
        </div>
      </div>
    </div>
  );
}
