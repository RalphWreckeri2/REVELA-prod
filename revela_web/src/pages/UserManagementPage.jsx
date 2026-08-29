import { useState, useEffect, useMemo, useCallback } from "react";
import DashboardLayout from "../components/DashboardLayout";
import { useAuth } from "../context/AuthContext";
import {
  getUsersRequest,
  createUserRequest,
  updateUserRequest,
  deleteUserRequest,
  API_ORIGIN,
} from "../services/api";
import "../styles/UserManagement.css";
import AnimatePresence from "../components/AnimatePresence";
import SwalOriginal from "sweetalert2";

const Swal = SwalOriginal.mixin({
  showClass: { popup: 'swal2-noanimation', backdrop: 'swal2-noanimation' },
  hideClass: { popup: '', backdrop: '' }
});

// ── SVG Icons ─────────────────────────────────────────────────────────────────
const Icons = {
  users: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  shield: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  clipboard: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><path d="M9 14l2 2 4-4"/></svg>,
  alertTriangle: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  edit: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  key: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>,
  trash: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
  plus: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  refresh: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
};

// ── Avatar ────────────────────────────────────────────────────────────────────
const AVATAR_COLORS = ["#56ab2f","#3b82f6","#8b5cf6","#ec4899","#f59e0b","#06b6d4","#ef4444","#10b981"];
function UserAvatar({ name, size = 38 }) {
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  const colorIdx = (name || "").split("").reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_COLORS.length;
  return (
    <div className="um-avatar" style={{ width: size, height: size, background: AVATAR_COLORS[colorIdx] }}>
      {initials}
    </div>
  );
}

// ── Role badge ────────────────────────────────────────────────────────────────
function RoleBadge({ role }) {
  const cfg = {
    SUPER_ADMIN: { cls: "um-badge--gold", label: "Super Admin" },
    Admin:       { cls: "um-badge--green", label: "Admin" },
    Inspector:   { cls: "um-badge--blue", label: "Inspector" },
  };
  const c = cfg[role] ?? { cls: "um-badge--muted", label: role };
  return <span className={`um-badge ${c.cls}`}>{c.label}</span>;
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ user }) {
  if (user.isActive === 0 || user.isActive === false) {
    return <span className="um-badge um-badge--danger">Deactivated</span>;
  }
  if (user.resetRequested) {
    return <span className="um-badge um-badge--danger um-badge--pulse">🚨 Reset Requested</span>;
  }
  if (user.mustChangePassword) {
    return <span className="um-badge um-badge--warning">Temp Password</span>;
  }
  return <span className="um-badge um-badge--success">Active</span>;
}

// ── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ icon, value, label, variant = "green" }) {
  return (
    <div className={`um-stat-card frosted-glass um-stat--${variant}`}>
      <div className={`um-stat-icon um-stat-icon--${variant}`}>{icon}</div>
      <div className="um-stat-info">
        <h3>{value}</h3>
        <p>{label}</p>
      </div>
    </div>
  );
}

// ── Copy to clipboard helper ──────────────────────────────────────────────────
function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button type="button" className="um-copy-btn" onClick={handleCopy} title="Copy to clipboard">
      <span className="um-copy-icon">{copied ? Icons.check : Icons.copy}</span>
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// ── Create Modal ──────────────────────────────────────────────────────────────
function CreateUserModal({ onClose, onSuccess, token }) {
  const [formData, setFormData] = useState({ fullName: "", email: "", role: "Admin", phone: "" });
  const [password, setPassword] = useState("");
  const [loading,  setLoading]  = useState(false);
  const [generating, setGenerating] = useState(false);

  const generatePassword = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_ORIGIN}/api/users/generate-password`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) setPassword(data.tempPassword);
    } catch (err) {
      console.error("Failed to generate password", err);
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => { generatePassword(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await createUserRequest({ ...formData, password }, token);
      onSuccess();
      Swal.fire({
        icon: 'success',
        title: 'User Created',
        text: `User "${formData.fullName}" created successfully. Temporary password: ${result.tempPassword || password}`
      });
      onClose();
    } catch (err) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: err.message || "Failed to create user."
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="um-backdrop" onClick={onClose}>
      <div className="um-modal" onClick={e => e.stopPropagation()}>
        <button className="um-modal-close" onClick={onClose}>✕</button>
        <div className="um-modal-header">
          <div className="um-modal-icon um-modal-icon--green">{Icons.plus}</div>
          <div>
            <h3 className="um-modal-title">Create New User</h3>
            <p className="um-modal-subtitle">Add a new team member to the system</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="um-form">
          {[
            { label: "Full Name",  key: "fullName", type: "text",  placeholder: "Juan Dela Cruz"                  },
            { label: "Email",      key: "email",    type: "email", placeholder: "juan@mataasnakahoy.gov.ph"        },
            { label: "Phone",      key: "phone",    type: "text",  placeholder: "+63 9XX XXX XXXX (optional)"     },
          ].map(f => (
            <div key={f.key} className="um-field">
              <label className="um-label">{f.label}</label>
              <input
                type={f.type}
                required={f.key !== "phone"}
                placeholder={f.placeholder}
                value={formData[f.key]}
                onChange={e => setFormData({ ...formData, [f.key]: e.target.value })}
                className="um-input"
              />
            </div>
          ))}

          <div className="um-field">
            <label className="um-label">Temporary Password</label>
            <div className="um-input-group">
              <input
                type="text"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="um-input"
                style={{ flex: 1 }}
              />
              <button type="button" className="ghost-btn um-btn-sm" onClick={generatePassword} disabled={generating}>
                {Icons.refresh}
                {generating ? "..." : "Random"}
              </button>
            </div>
            <span className="um-hint">User will be required to change this on first login.</span>
          </div>

          <div className="um-field">
            <label className="um-label">Role</label>
            <select
              value={formData.role}
              onChange={e => setFormData({ ...formData, role: e.target.value })}
              className="um-input"
            >
              <option value="Admin">Admin</option>
              <option value="Inspector">Inspector</option>
            </select>
          </div>

          <div className="um-modal-actions">
            <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-btn" disabled={loading}>
              {loading ? "Creating…" : "Create User"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Edit Modal ────────────────────────────────────────────────────────────────
function EditUserModal({ user, onClose, onSuccess, token }) {
  const [formData, setFormData] = useState({
    fullName: user.fullName,
    email:    user.email,
    role:     user.userRole,
    phone:    user.phone ?? "",
  });
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await updateUserRequest(user.userID, formData, token);
      onSuccess();
      Swal.fire({
        icon: 'success',
        title: 'User Updated',
        text: 'User details updated successfully.'
      });
      onClose();
    } catch (err) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: err.message || "Failed to update user."
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="um-backdrop" onClick={onClose}>
      <div className="um-modal" onClick={e => e.stopPropagation()}>
        <button className="um-modal-close" onClick={onClose}>✕</button>
        <div className="um-modal-header">
          <div className="um-modal-icon um-modal-icon--blue">{Icons.edit}</div>
          <div>
            <h3 className="um-modal-title">Edit User</h3>
            <p className="um-modal-subtitle">Update details for {user.fullName}</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="um-form">
          {[
            { label: "Full Name", key: "fullName", type: "text"  },
            { label: "Email",     key: "email",    type: "email" },
            { label: "Phone",     key: "phone",    type: "text"  },
          ].map(f => (
            <div key={f.key} className="um-field">
              <label className="um-label">{f.label}</label>
              <input
                type={f.type}
                required={f.key !== "phone"}
                value={formData[f.key]}
                onChange={e => setFormData({ ...formData, [f.key]: e.target.value })}
                className="um-input"
              />
            </div>
          ))}

          {user.userRole !== "SUPER_ADMIN" ? (
            <div className="um-field">
              <label className="um-label">Role</label>
              <select
                value={formData.role}
                onChange={e => setFormData({ ...formData, role: e.target.value })}
                className="um-input"
              >
                <option value="Admin">Admin</option>
                <option value="Inspector">Inspector</option>
              </select>
            </div>
          ) : (
            <div className="um-field">
              <label className="um-label">Role</label>
              <input
                disabled
                value="SUPER_ADMIN"
                className="um-input um-input--disabled"
              />
              <span className="um-hint">🔒 This role is permanently locked and cannot be changed.</span>
            </div>
          )}

          <div className="um-modal-actions">
            <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-btn" disabled={loading}>
              {loading ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Delete Modal ──────────────────────────────────────────────────────────────
function DeleteUserModal({ targetUser, onClose, onSuccess, token }) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await deleteUserRequest(targetUser.userID, token);
      onSuccess();
      Swal.fire({
        icon: 'success',
        title: 'User Removed',
        text: 'User has been removed successfully.'
      });
      onClose();
    } catch (err) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: err.message || "Failed to remove user."
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="um-backdrop" onClick={onClose}>
      <div className="um-modal" onClick={e => e.stopPropagation()}>
        <button className="um-modal-close" onClick={onClose}>✕</button>
        <div className="um-modal-header">
          <div className="um-modal-icon um-modal-icon--red">{Icons.trash}</div>
          <div>
            <h3 className="um-modal-title">Remove User</h3>
            <p className="um-modal-subtitle">This action cannot be undone</p>
          </div>
        </div>

        <p className="um-confirm-text">
          Are you sure you want to permanently remove <strong>{targetUser.fullName}</strong>?
          All their access will be revoked immediately.
        </p>

        <div className="um-modal-actions">
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="primary-btn um-btn--danger" onClick={handleConfirm} disabled={loading}>
            {loading ? "Removing…" : "Remove User"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Reset Password Modal ──────────────────────────────────────────────────────
function ResetPasswordModal({ targetUser, onClose, onSuccess, token }) {
  const [loading, setLoading] = useState(false);
  const [newPass, setNewPass] = useState("");

  const handleConfirm = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_ORIGIN}/api/users/${targetUser.userID}/reset-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({})
      });
      
      let data;
      const text = await res.text();
      try {
        data = JSON.parse(text);
      } catch (parseErr) {
        throw new Error(`Server returned ${res.status}: ${text.slice(0, 60)}...`);
      }

      if (!res.ok) throw new Error(data?.error || "Failed to reset password.");
      setNewPass(data.tempPassword);
      if (onSuccess) onSuccess();
      Swal.fire({
        icon: 'success',
        title: 'Password Reset',
        text: 'Password has been successfully reset.'
      });
    } catch (err) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: err.message || "Failed to reset password."
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="um-backdrop" onClick={!newPass ? onClose : undefined}>
      <div className="um-modal" onClick={e => e.stopPropagation()}>
        <button className="um-modal-close" onClick={onClose}>✕</button>
        <div className="um-modal-header">
          <div className="um-modal-icon um-modal-icon--gold">{Icons.key}</div>
          <div>
            <h3 className="um-modal-title">Reset Password</h3>
            <p className="um-modal-subtitle">{targetUser.fullName}</p>
          </div>
        </div>
        {newPass ? (
          <div>
            <div className="um-password-result">
              <label className="um-label">New Temporary Password</label>
              <div className="um-password-display">
                <span className="um-password-value">{newPass}</span>
                <CopyButton text={newPass} />
              </div>
              <p className="um-hint" style={{ marginTop: 8 }}>
                Please securely send this to the user. They will be forced to change it on their next login.
              </p>
            </div>
            <div className="um-modal-actions">
              <button type="button" className="primary-btn" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <div>
            <p className="um-confirm-text">
              Are you sure you want to reset the password for <strong>{targetUser.fullName}</strong>?
              This will invalidate their current password immediately.
            </p>
            <div className="um-modal-actions">
              <button type="button" className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
              <button type="button" className="primary-btn" onClick={handleConfirm} disabled={loading}>
                {loading ? "Resetting…" : "Reset Password"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function UserManagementPage() {
  const { token, user } = useAuth();
  const [users,          setUsers]          = useState([]);
  const [loading,        setLoading]        = useState(true);
  const [showCreate,     setShowCreate]     = useState(false);
  const [editingUser,    setEditingUser]    = useState(null);
  const [userToDelete,   setUserToDelete]   = useState(null);
  const [userToReset,    setUserToReset]    = useState(null);
  const [search,         setSearch]         = useState("");
  const [roleFilter,     setRoleFilter]     = useState("all");
  const [isRefreshing,   setIsRefreshing]   = useState(false);

  const fetchUsers = useCallback(async (isSilent = false) => {
    if (!token) return;
    if (!isSilent) {
      setLoading(true);
      setIsRefreshing(true);
    }
    try {
      const data = await getUsersRequest(token);
      setUsers(data.filter(u => u.isActive !== 0 && u.isActive !== false));
    } catch (err) {
      if (!isSilent) {
        Swal.fire({
          icon: 'error',
          title: 'Error',
          text: err.message || "Failed to load users."
        });
      }
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [token]);

  useEffect(() => { 
    fetchUsers(false); 
    const handleSync = () => {
      fetchUsers(true);
    };

    window.addEventListener("revela:password-reset", handleSync);
    window.addEventListener("revela:user-update", handleSync);
    window.addEventListener("revela:global-refresh", handleSync);

    const pollTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchUsers(true);
      }
    }, 30000);

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchUsers(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.removeEventListener("revela:password-reset", handleSync);
      window.removeEventListener("revela:user-update", handleSync);
      window.removeEventListener("revela:global-refresh", handleSync);
      window.clearInterval(pollTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [fetchUsers]);

  // Derived stats
  const stats = useMemo(() => {
    const total = users.length;
    const active = users.filter(u => (u.isActive !== 0 && u.isActive !== false) && !u.mustChangePassword).length;
    const inspectors = users.filter(u => u.userRole === "Inspector").length;
    const admins = users.filter(u => u.userRole === "Admin" || u.userRole === "SUPER_ADMIN" || u.userRole === "System Administrator").length;
    const pendingResets = users.filter(u => u.resetRequested).length;
    return { total, active, inspectors, admins, pendingResets };
  }, [users]);

  // Filtered users
  const filteredUsers = useMemo(() => {
    return users.filter(u => {
      const q = search.toLowerCase();
      const matchesSearch = !q || u.fullName.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || (u.phone || "").includes(q);
      const matchesRole = roleFilter === "all" || u.userRole === roleFilter;
      return matchesSearch && matchesRole;
    });
  }, [users, search, roleFilter]);

  // ── Access control ────────────────────────────────────────────────────────
  if (user?.role !== "SUPER_ADMIN") {
    return (
      <DashboardLayout>
        <div className="page-header">
          <h1 className="page-title">User Management</h1>
        </div>
        <div className="saas-card frosted-glass" style={{ textAlign: "center", padding: "80px 20px" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🔒</div>
          <h2 style={{ fontSize: 20, color: "var(--color-ink)", marginBottom: 8 }}>Access Restricted</h2>
          <p style={{ color: "var(--color-muted)", maxWidth: 400, margin: "0 auto" }}>
            User management is strictly reserved for Super Administrators.
          </p>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">User Management</h1>
          <p className="page-subtitle">Manage system access, roles, and administrator accounts.</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            className="quick-refresh-btn"
            type="button"
            onClick={() => fetchUsers(false)}
            disabled={isRefreshing}
            title="Refresh user list"
          >
            <svg
              className={isRefreshing ? "spin-icon" : ""}
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" />
            </svg>
            <span>{isRefreshing ? "Syncing…" : "Refresh"}</span>
          </button>
          <button className="primary-btn" type="button" onClick={() => setShowCreate(true)}>
            {Icons.plus} Create User
          </button>
        </div>
      </div>

      {/* Banners */}

      {stats.pendingResets > 0 && (
        <div className="um-alert um-alert--error" style={{ background: "var(--color-danger)", color: "#fff", border: "none", boxShadow: "0 10px 25px rgba(239, 68, 68, 0.4)", animation: "um-pulse 2s infinite" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ background: "rgba(255,255,255,0.2)", padding: 6, borderRadius: "50%", display: "flex" }}>{Icons.alertTriangle}</span>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <strong style={{ fontSize: 16 }}>Action Required: Pending Password Resets</strong>
              <span style={{ fontSize: 13, opacity: 0.9 }}>{stats.pendingResets} user{stats.pendingResets > 1 ? 's have' : ' has'} requested a password reset. Please review the list below.</span>
            </div>
          </div>
        </div>
      )}

      {/* Stat Cards */}
      <div className="um-stats-grid">
        <StatCard icon={Icons.users} value={stats.total} label="Total Users" variant="green" />
        <StatCard icon={Icons.shield} value={stats.admins} label="Administrators" variant="gold" />
        <StatCard icon={Icons.clipboard} value={stats.inspectors} label="Inspectors" variant="blue" />
        {stats.pendingResets > 0 && (
          <StatCard icon={Icons.alertTriangle} value={stats.pendingResets} label="Pending Resets" variant="red" />
        )}
      </div>

      {/* Table Card */}
      <div className="saas-card frosted-glass um-table-card">
        {/* Toolbar */}
        <div className="um-toolbar">
          <div className="um-search">
            {Icons.search}
            <input
              type="text"
              placeholder="Search by name, email, or phone…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="um-filters">
            {["all", "Admin", "Inspector", "SUPER_ADMIN"].map(r => (
              <button
                key={r}
                className={`um-filter-btn ${roleFilter === r ? "um-filter-btn--active" : ""}`}
                onClick={() => setRoleFilter(r)}
              >
                {r === "all" ? "All Roles" : r === "SUPER_ADMIN" ? "Super Admin" : r}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="um-table-wrapper">
          <table className="um-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Contact</th>
                <th>Last Login</th>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="um-table-empty">
                    <div className="um-spinner" />
                    <span>Loading users…</span>
                  </td>
                </tr>
              ) : filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="um-table-empty">
                    <img src="/searching.png" alt="No users found" style={{ height: 100, objectFit: "contain", opacity: 0.9, marginBottom: 12 }} />
                    <span>{search || roleFilter !== "all" ? "No users match your filters." : 'No users found. Click "Create User" to add one.'}</span>
                  </td>
                </tr>
              ) : filteredUsers.map((u) => (
                <tr key={u.userID} className="um-row">
                  <td>
                    <div className="um-user-cell">
                      <UserAvatar name={u.fullName} />
                      <div>
                        <div className="um-user-name">
                          {u.fullName}
                          {u.userID === user.userID && (
                            <span className="um-you-badge">You</span>
                          )}
                        </div>
                        <div className="um-user-email">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td><RoleBadge role={u.userRole} /></td>
                  <td className="um-cell-muted">{u.phone || "—"}</td>
                  <td className="um-cell-muted">
                    {u.lastLoginAt ? new Date(u.lastLoginAt).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "Never"}
                  </td>
                  <td><StatusBadge user={u} /></td>
                  <td>
                    <div className="um-actions">
                      <button
                        className="um-action-btn"
                        title="Edit user"
                        onClick={() => setEditingUser(u)}
                      >
                        {Icons.edit}
                      </button>
                      {u.userID !== user.userID && u.isActive !== 0 && u.isActive !== false && (
                        <>
                          <button
                            className="um-action-btn um-action-btn--primary"
                            title="Reset password"
                            onClick={() => setUserToReset(u)}
                          >
                            {Icons.key}
                          </button>
                          <button
                            className="um-action-btn um-action-btn--danger"
                            title="Remove user"
                            onClick={() => setUserToDelete(u)}
                          >
                            {Icons.trash}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Table footer */}
        {!loading && filteredUsers.length > 0 && (
          <div className="um-table-footer">
            Showing {filteredUsers.length} of {users.length} user{users.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>

      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
      </footer>

      {/* Modals */}
      <AnimatePresence isVisible={showCreate}>
        <CreateUserModal
          token={token}
          onClose={() => setShowCreate(false)}
          onSuccess={fetchUsers}
        />
      </AnimatePresence>

      <AnimatePresence isVisible={!!editingUser}>
        <EditUserModal
          user={editingUser}
          token={token}
          onClose={() => setEditingUser(null)}
          onSuccess={fetchUsers}
        />
      </AnimatePresence>

      <AnimatePresence isVisible={!!userToDelete}>
        <DeleteUserModal
          targetUser={userToDelete}
          token={token}
          onClose={() => setUserToDelete(null)}
          onSuccess={() => {
            fetchUsers();
          }}
        />
      </AnimatePresence>

      <AnimatePresence isVisible={!!userToReset}>
        <ResetPasswordModal
          targetUser={userToReset}
          token={token}
          onClose={() => setUserToReset(null)}
          onSuccess={fetchUsers}
        />
      </AnimatePresence>
    </DashboardLayout>
  );
}