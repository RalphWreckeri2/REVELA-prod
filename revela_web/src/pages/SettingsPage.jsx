import { useState, useEffect, useRef, useContext } from "react";
import { useTheme } from "../context/ThemeContext";
import DashboardLayout from "../components/DashboardLayout";
import { AuthContext } from "../context/AuthContext";
import { changePasswordRequest, setup2faRequest, verify2faSetupRequest } from "../services/authService";
import Swal from "sweetalert2";
import { QRCodeSVG } from "qrcode.react";
import { getWlcConfigRequest, updateWlcConfigRequest, updateMePreferencesRequest, API_ORIGIN } from "../services/api";
import { useLoadScript, GoogleMap, Marker } from "@react-google-maps/api";
import { darkMapStyle, REVELA_MAP_ID } from "../utils/mapStyles";
import TermsPage from "../components/TermsPage";
import PrivacyPage from "../components/PrivacyPage";
import AnimatePresence from "../components/AnimatePresence";
import { createPortal } from "react-dom";

const LIBRARIES = ["places"];

// ── Icons ─────────────────────────────────────────────────────────────────────
const EyeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EyeOffIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
);

// ── Legal Document Modal ──────────────────────────────────────────────────────
function LegalDocModal({ title, children, onClose, isClosing }) {
  // Rendered via portal so the modal escapes the `.saas-content` stacking context
  // (z-index 10) and sits ABOVE the sticky top navbar (z-index 20).
  return createPortal(
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "rgba(15, 23, 42, 0.55)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
      }}
      className={"modal-backdrop" + (isClosing ? " closing" : "")}
      onClick={onClose}
    >
      <div
        className={"modal-panel" + (isClosing ? " closing" : "")}
        style={{
          background: "var(--color-modal-bg)", borderRadius: 16,
          width: "min(100%, 800px)", height: "min(90vh, 800px)",
          display: "flex", flexDirection: "column",
          boxShadow: "0 20px 50px rgba(0,0,0,0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid var(--color-border-soft)" }}>
          <h3 style={{ margin: 0, fontSize: 16, color: "var(--color-ink)" }}>{title}</h3>
          <button className="modal-close-btn" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>{children}</div>
      </div>
    </div>,
    document.body
  );
}

// ── Change Password Modal ─────────────────────────────────────────────────────
function ChangePasswordModal({ onClose, token, isClosing }) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showOldPassword, setShowOldPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!oldPassword || !newPassword) return;
    setLoading(true);
    setError("");
    try {
      await changePasswordRequest({ oldPassword, newPassword }, token);

      Swal.fire({
        icon: 'success',
        title: 'Password Updated',
        text: 'Your password was successfully changed.',
        confirmButtonColor: '#56ab2f'
      });
      onClose();
    } catch (err) {
      setError(err.message || "Failed to change password.");
    } finally {
      setLoading(false);
    }
  };

  // Portal: escape the .saas-content stacking context so the modal clears the navbar
  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }} onClick={onClose}>
      <div className={"modal-panel saas-card frosted-glass" + (isClosing ? " closing" : "")} style={{ width: "min(100%, 400px)", padding: 32, position: "relative", background: "var(--color-modal-bg)", boxShadow: "0 24px 60px rgba(15,23,42,0.18)" }} onClick={e => e.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose} style={{ position: "absolute", top: 16, right: 16 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
        <h3 style={{ margin: "0 0 20px 0", fontSize: 18, color: "var(--color-ink)" }}>Change Password</h3>

        {error && <p style={{ background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "var(--color-danger)", marginBottom: 16 }}>{error}</p>}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>Current Password</label>
            <div style={{ position: "relative" }}>
              <input type={showOldPassword ? "text" : "password"} value={oldPassword} onChange={e => setOldPassword(e.target.value)} required style={{ width: "100%", padding: "10px 36px 10px 12px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-input-bg)", fontSize: 14, boxSizing: "border-box" }} />
              <button type="button" onClick={() => setShowOldPassword(!showOldPassword)} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--color-muted)", display: "flex", padding: 0 }}>
                {showOldPassword ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>New Password</label>
            <div style={{ position: "relative" }}>
              <input type={showNewPassword ? "text" : "password"} value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={8} style={{ width: "100%", padding: "10px 36px 10px 12px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-input-bg)", fontSize: 14, boxSizing: "border-box" }} />
              <button type="button" onClick={() => setShowNewPassword(!showNewPassword)} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--color-muted)", display: "flex", padding: 0 }}>
                {showNewPassword ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 8 }}>
            <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-btn" disabled={loading}>{loading ? "Updating..." : "Update Password"}</button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

// ── Setup 2FA Modal ───────────────────────────────────────────────────────────
function Setup2FAModal({ onClose, token, onSuccess, isClosing }) {
  const [secret, setSecret] = useState("");
  const [otpUri, setOtpUri] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function fetchSetup() {
      try {
        const res = await setup2faRequest(token);
        if (!cancelled) {
          setSecret(res.secret);
          setOtpUri(res.otpUri);
        }
      } catch (err) {
        if (!cancelled) setError("Failed to initialize 2FA setup.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchSetup();
    return () => { cancelled = true; };
  }, [token]);

  const handleVerify = async (e) => {
    e.preventDefault();
    if (!code || code.length !== 6) return;
    setVerifying(true);
    setError("");
    try {
      await verify2faSetupRequest({ code }, token);
      Swal.fire({ icon: 'success', title: '2FA Enabled', text: 'Two-factor authentication is now active.', confirmButtonColor: '#56ab2f' });
      if (onSuccess) onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || "Invalid code. Please try again.");
    } finally {
      setVerifying(false);
    }
  };

  // Portal: escape the .saas-content stacking context so the modal clears the navbar
  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }} onClick={onClose}>
      <div className={"modal-panel saas-card frosted-glass" + (isClosing ? " closing" : "")} style={{ width: "min(100%, 400px)", padding: 32, position: "relative", background: "var(--color-modal-bg)", boxShadow: "0 24px 60px rgba(15,23,42,0.18)" }} onClick={e => e.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose} style={{ position: "absolute", top: 16, right: 16 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
        <h3 style={{ margin: "0 0 20px 0", fontSize: 18, color: "var(--color-ink)" }}>Set up Two-Factor Auth</h3>
        {error && <p style={{ background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "var(--color-danger)", marginBottom: 16 }}>{error}</p>}

        {loading ? (
          <p style={{ fontSize: 14, color: "var(--color-muted)" }}>Generating secure keys...</p>
        ) : (
          <form onSubmit={handleVerify} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>1. Scan this QR code with Google Authenticator or Authy:</p>
            <div style={{ display: "flex", justifyContent: "center", background: "var(--color-modal-bg)", padding: "16px", borderRadius: "8px", border: "1px dashed var(--color-border)" }}>
              {otpUri && <QRCodeSVG value={otpUri} size={150} level="M" />}
            </div>
            <p style={{ fontSize: 12, color: "var(--color-muted)", textAlign: "center", margin: 0 }}>Or enter this setup key manually:</p>
            <div style={{ background: "var(--color-hover)", padding: "8px 12px", borderRadius: "8px", textAlign: "center", fontWeight: "700", letterSpacing: "2px", color: "var(--color-primary)", wordBreak: "break-word", fontFamily: "monospace", fontSize: 14 }}>{secret.match(/.{1,4}/g)?.join(' ') || secret}</div>
            <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>2. Enter the 6-digit code generated by the app to verify.</p>
            <input type="text" placeholder="123456" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ""))} required style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-input-bg)", fontSize: 16, textAlign: "center", letterSpacing: "4px" }} />

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 8 }}>
              <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={verifying || code.length < 6}>{verifying ? "Verifying..." : "Verify & Enable"}</button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body
  );
}

// ── Map Picker Modal ──────────────────────────────────────────────────────────
// Rendered through <AnimatePresence>, which injects an `isClosing` prop during
// the exit animation — a raw DOM <div> can't receive it, hence this component.
function MapPickerModal({ isLoaded, loadError, isDark, center, marker, onPick, onClose, isClosing }) {
  // Portal: escape the .saas-content stacking context so the modal clears the navbar
  return createPortal(
    <div
      className={"modal-backdrop" + (isClosing ? " closing" : "")}
      style={{
        position: "fixed", top: 0, left: 0, width: "100%", height: "100%",
        background: "rgba(15,23,42,0.6)", backdropFilter: "blur(4px)",
        display: "flex", justifyContent: "center", alignItems: "center",
        zIndex: 99999
      }}
    >
      <div
        className={"modal-panel" + (isClosing ? " closing" : "")}
        style={{
          background: "var(--color-modal-bg)", borderRadius: 16, padding: 24,
          width: "90%", maxWidth: 600,
          boxShadow: "0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)"
        }}
      >
        <h3 style={{ margin: "0 0 16px", color: "var(--color-ink)", fontSize: 18, fontWeight: 700 }}>Select Base Station Location</h3>
        <p style={{ margin: "0 0 16px", color: "var(--color-muted)", fontSize: 13 }}>Click anywhere on the map to set the BPLO office coordinates.</p>

        <div style={{ position: "relative", width: "100%", height: 350, borderRadius: 12, overflow: "hidden", border: "1px solid var(--color-border)" }}>
          {isLoaded && !loadError ? (
            <GoogleMap
              mapContainerStyle={{ width: "100%", height: "100%" }}
              center={center}
              zoom={15}
              options={{
                disableDefaultUI: true,
                zoomControl: true,
                clickableIcons: false, // POI clicks must not swallow map picks
                mapId: REVELA_MAP_ID,
                colorScheme: isDark ? "DARK" : "LIGHT",
              }}
              onClick={(e) => {
                if (!e.latLng) return; // guard: some click events carry no coordinates
                onPick({
                  lat: parseFloat(e.latLng.lat().toFixed(6)),
                  lng: parseFloat(e.latLng.lng().toFixed(6)),
                });
              }}
            >
              {marker && <Marker position={marker} />}
            </GoogleMap>
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-muted)", fontSize: 13, padding: 24, textAlign: "center" }}>
              {loadError ? "Failed to load Google Maps. Please check your connection or API key." : "Loading map…"}
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20 }}>
          <button
            type="button"
            className="ghost-btn"
            onClick={onClose}
            style={{ padding: "8px 16px", background: "var(--color-surface)", color: "var(--color-muted)" }}
          >
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default function SettingsPage() {
  const { token, user, refreshUser } = useContext(AuthContext);
  const [emailAlerts, setEmailAlerts] = useState(true);
  const { theme, previewTheme, isDark, setTheme, setPreviewTheme } = useTheme();

  const activeTheme = previewTheme || theme;

  const [savingPreferences, setSavingPreferences] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);

  const [showMapModal, setShowMapModal] = useState(false);
  const { isLoaded, loadError } = useLoadScript({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY,
    libraries: LIBRARIES,
    // Keep in sync with MapPage/HomePage — mixing script versions can double-load the Maps API
    version: "beta",
  });
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [show2FAModal, setShow2FAModal] = useState(false);
  const [showTermsDoc, setShowTermsDoc] = useState(false);
  const [showPrivacyDoc, setShowPrivacyDoc] = useState(false);
  const [wlcConfig, setWlcConfig] = useState({ w1_risk: 68, w2_sector: 7, w3_distance: 25, bplo_lat: 13.960413, bplo_lng: 121.114547 });
  const [sectors, setSectors] = useState([]);

  const SECTOR_OPTIONS = ["Food Service", "Retail", "Manufacturing", "Healthcare", "Education", "Real Estate", "Logistics", "Other"];

  // Load initial settings on mount
  useEffect(() => {
    const savedEmailAlerts = localStorage.getItem("revela_emailAlerts");

    if (user != null && typeof user.emailInspectionAlerts === "boolean") {
      setEmailAlerts(user.emailInspectionAlerts);
    } else if (savedEmailAlerts !== null) {
      setEmailAlerts(savedEmailAlerts === "true");
    }

    getWlcConfigRequest(token).then(data => {
      if (data) {
        setWlcConfig(data);
        if (data.sectors) {
          const loadedSectors = Object.entries(data.sectors).map(([name, score]) => ({ name, score }));
          setSectors(loadedSectors);
        }
      }
    }).catch(console.error);

    return () => {
      // Clear preview theme on unmount so it reverts if unsaved
      setPreviewTheme(null);
    };
  }, [token, user, setPreviewTheme]);

  const handleSavePreferences = async () => {
    setSavingPreferences(true);
    localStorage.setItem("revela_emailAlerts", emailAlerts);
    if (previewTheme) {
      setTheme(previewTheme);
    }
    try {
      await updateMePreferencesRequest({ emailInspectionAlerts: emailAlerts }, token);
      if (refreshUser) await refreshUser();
      Swal.fire({
        icon: "success",
        title: "Saved",
        text: "Preferences synced to your account.",
        timer: 2000,
        showConfirmButton: false,
      });
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Save failed",
        text: err.message || "Could not update notification preferences on the server.",
      });
    } finally {
      setSavingPreferences(false);
    }
  };

  const handleSavePolicy = async () => {
    setSavingPolicy(true);

    try {
      const sectorObj = {};
      sectors.forEach(s => { if (s.name) sectorObj[s.name] = Number(s.score); });

      await updateWlcConfigRequest({ ...wlcConfig, sectors: sectorObj }, token);
      Swal.fire({ icon: 'success', title: 'Saved', text: 'Settings updated successfully.', timer: 2000, showConfirmButton: false });
    } catch (err) {
      Swal.fire('Error', err.message || "Failed to update WLC config", 'error');
    }
    setSavingPolicy(false);
  };

  const handleToggle2FA = async () => {
    if (user?.is_2fa_enabled) {
      Swal.fire({
        title: 'Disable 2FA?',
        text: "Are you sure you want to disable Two-Factor Authentication?",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, disable it'
      }).then(async (result) => {
        if (result.isConfirmed) {
          try {
            const res = await fetch(`${API_ORIGIN}/api/auth/disable-2fa`, {
              method: "POST",
              headers: { "Authorization": `Bearer ${token}` }
            });
            if (!res.ok) {
              const data = await res.json().catch(() => ({}));
              throw new Error(data.error || "Failed to disable 2FA");
            }
            Swal.fire('Disabled!', '2FA has been disabled.', 'success');
            if (refreshUser) refreshUser();
          } catch (err) {
            Swal.fire('Error', err.message, 'error');
          }
        }
      });
    } else {
      setShow2FAModal(true);
    }
  };

  const handleWeightChange = (changedKey, newValue) => {
    let val = Math.min(100, Math.max(0, parseInt(newValue || 0, 10)));
    const otherKeys = ["w1_risk", "w2_sector", "w3_distance"].filter(k => k !== changedKey);
    let remaining = 100 - val;

    let k1 = otherKeys[0];
    let k2 = otherKeys[1];
    let sumOthers = wlcConfig[k1] + wlcConfig[k2];

    let newWlc = { ...wlcConfig, [changedKey]: val };
    if (sumOthers === 0) {
      newWlc[k1] = Math.floor(remaining / 2);
      newWlc[k2] = remaining - newWlc[k1];
    } else {
      newWlc[k1] = Math.round((wlcConfig[k1] / sumOthers) * remaining);
      newWlc[k2] = remaining - newWlc[k1];
    }
    setWlcConfig(newWlc);
  };

  const DEFAULT_WLC = { w1_risk: 68, w2_sector: 7, w3_distance: 25 };

  const applyPreset = (preset) => {
    if (preset === "ahp" || preset === "default") {
      setWlcConfig(prev => ({ ...prev, ...DEFAULT_WLC }));
    }
    if (preset === "health") setWlcConfig(prev => ({ ...prev, w1_risk: 20, w2_sector: 70, w3_distance: 10 }));
    if (preset === "renewal") setWlcConfig(prev => ({ ...prev, w1_risk: 70, w2_sector: 20, w3_distance: 10 }));
  };

  const addSector = () => setSectors([...sectors, { name: "", score: 50 }]);
  const updateSector = (index, field, value) => {
    const newSectors = [...sectors];
    newSectors[index][field] = value;
    setSectors(newSectors);
  };
  const removeSector = (index) => setSectors(sectors.filter((_, i) => i !== index));

  const handleUseCurrentLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setWlcConfig(prev => ({
            ...prev,
            bplo_lat: parseFloat(position.coords.latitude.toFixed(6)),
            bplo_lng: parseFloat(position.coords.longitude.toFixed(6))
          }));
          Swal.fire({
            title: "Location Updated",
            text: "Coordinates have been updated to your current location.",
            icon: "success",
            timer: 2000,
            showConfirmButton: false,
            toast: true,
            position: 'top-end'
          });
        },
        (error) => {
          Swal.fire("Error", "Could not get your current location. Please check your browser permissions.", "error");
        }
      );
    } else {
      Swal.fire("Error", "Geolocation is not supported by this browser.", "error");
    }
  };

  if (!token) return null;

  return (
    <DashboardLayout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Configure dashboard preferences and system behavior.</p>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Local UI Preferences */}
        <section className="saas-card frosted-glass">
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ margin: "0 0 8px", color: "var(--color-ink)", fontSize: 18 }}>Local UI Preferences</h3>
            <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13 }}>Control dashboard alerts and appearance. Email inspection alerts are saved to your account and used when inspectors submit field evidence.</p>
          </div>
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20 }}>
              <span style={{ fontSize: 14, fontWeight: 500, color: "var(--color-ink)" }}>Email notifications (inspection evidence submitted)</span>
              <div style={{
                display: "inline-flex",
                background: "var(--color-hover)",
                borderRadius: 12,
                padding: 4,
                border: "1px solid var(--color-border-soft)",
              }}>
                {[{ label: "On", value: true }, { label: "Off", value: false }].map(opt => {
                  const isActive = emailAlerts === opt.value;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      onClick={() => setEmailAlerts(opt.value)}
                      style={{
                        display: "inline-flex", alignItems: "center", padding: "8px 16px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 13,
                        fontWeight: isActive ? 600 : 500, fontFamily: "inherit",
                        background: isActive ? "var(--color-primary)" : "transparent",
                        color: isActive ? "#fff" : "var(--color-muted)",
                        transition: "all 0.2s ease",
                        boxShadow: isActive ? "0 2px 8px rgba(86, 171, 47, 0.3)" : "none",
                      }}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Theme Selector */}
            <div>
              <span style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 500, color: "var(--color-ink)" }}>Appearance</span>
              <div style={{
                display: "inline-flex",
                background: "var(--color-hover)",
                borderRadius: 12,
                padding: 4,
                border: "1px solid var(--color-border-soft)",
                position: "relative",
              }}>
                {[
                  {
                    value: "light", label: "Light", icon: (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="5" />
                        <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                        <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                      </svg>
                    )
                  },
                  {
                    value: "system", label: "System", icon: (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                        <line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
                      </svg>
                    )
                  },
                  {
                    value: "dark", label: "Dark", icon: (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                      </svg>
                    )
                  },
                ].map(opt => {
                  const isActive = activeTheme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setPreviewTheme(opt.value)}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 16px",
                        borderRadius: 8,
                        border: "none",
                        cursor: "pointer",
                        fontSize: 13,
                        fontWeight: isActive ? 600 : 500,
                        fontFamily: "inherit",
                        background: isActive ? "var(--color-primary)" : "transparent",
                        color: isActive ? "#fff" : "var(--color-muted)",
                        transition: "all 0.2s ease",
                        boxShadow: isActive ? "0 2px 8px rgba(86, 171, 47, 0.3)" : "none",
                      }}
                    >
                      {opt.icon}
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
              <button className="primary-btn" type="button" onClick={handleSavePreferences} disabled={savingPreferences}>
                {savingPreferences ? "Saving..." : "Save Preferences"}
              </button>
            </div>
          </div>
        </section>

        {/* System Policy (OPS WLC) */}
        <section className="saas-card frosted-glass">
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ margin: "0 0 8px", color: "var(--color-ink)", fontSize: 18 }}>System Policy (OPS WLC)</h3>
            <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13 }}>Set up priority score scenarios, linked weights, and dynamic sector rules.</p>
          </div>
          <div style={{ display: "grid", gap: 16 }}>
            {/* Scenario Presets */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ink)" }}>Apply Preset:</span>
              <button
                type="button"
                className="ghost-btn"
                style={{
                  padding: "6px 12px",
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--color-primary, #10b981)",
                  border: "1px solid var(--color-primary, #10b981)",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6
                }}
                onClick={() => applyPreset("default")}
                title="Reset to system default: 68% Risk, 7% Sector, 25% Distance"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                Use Default (68/7/25)
              </button>
              <button type="button" className="ghost-btn" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => applyPreset("health")}>
                Health Crisis Mode
              </button>
              <button type="button" className="ghost-btn" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => applyPreset("renewal")}>
                Business Renewal Peak
              </button>
            </div>

            {/* Linked Sliders */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "16px 0", borderTop: "1px solid var(--color-border-soft)", borderBottom: "1px solid var(--color-border-soft)", margin: "8px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <label style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)" }}>Linked Priority Weights</label>
                  <button
                    type="button"
                    className="ghost-btn"
                    style={{
                      padding: "3px 8px",
                      fontSize: 11,
                      fontWeight: 600,
                      color: "var(--color-primary, #10b981)",
                      border: "1px solid var(--color-border)",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4
                    }}
                    onClick={() => applyPreset("default")}
                    title="Reset to default weights (68% / 7% / 25%)"
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                    Use Default
                  </button>
                </div>
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-primary)" }}>
                  Total: {wlcConfig.w1_risk + wlcConfig.w2_sector + wlcConfig.w3_distance}%
                </span>
              </div>
              {[
                { key: "w1_risk", label: "Risk Volume (W1)" },
                { key: "w2_sector", label: "Sector Impact (W2)" },
                { key: "w3_distance", label: "Travel Distance (W3)" }
              ].map(w => (
                <div key={w.key} style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <span style={{ width: 140, fontSize: 12, fontWeight: 600, color: "var(--color-muted)" }}>{w.label}</span>
                  <input type="range" min="0" max="100" value={wlcConfig[w.key]} onChange={e => handleWeightChange(w.key, e.target.value)} style={{ flex: 1, accentColor: "var(--color-primary)" }} />
                  <div style={{ width: 30, textAlign: "right", fontSize: 13, fontWeight: 700, color: "var(--color-ink)" }}>{wlcConfig[w.key]}%</div>
                </div>
              ))}
            </div>

            {/* Dynamic Sector List */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <label style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)" }}>Sector Severity Settings</label>
                <button type="button" className="ghost-btn" style={{ padding: "4px 10px", fontSize: 12 }} onClick={addSector}>+ Add Sector</button>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {sectors.length === 0 && <p style={{ fontSize: 12, color: "var(--color-muted)" }}>No sector policies defined. Click "Add Sector" to set custom severities.</p>}
                {sectors.map((sec, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, background: "var(--color-input-bg)", padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                    <select value={sec.name} onChange={e => updateSector(i, "name", e.target.value)} style={{ padding: "6px", borderRadius: 6, border: "1px solid var(--color-border)", fontSize: 13, width: 160, background: "var(--color-modal-bg)" }}>
                      <option value="">Select Sector ▾</option>
                      {SECTOR_OPTIONS.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-muted)" }}>Severity:</span>
                    <input type="range" min="0" max="100" value={sec.score} onChange={e => updateSector(i, "score", e.target.value)} style={{ flex: 1, accentColor: "var(--color-primary)" }} />
                    <span style={{ width: 36, fontSize: 12, fontWeight: 700, color: "var(--color-ink)", textAlign: "right" }}>{(sec.score / 100).toFixed(1)}</span>
                    <button type="button" onClick={() => removeSector(i)} style={{ background: "none", border: "none", color: "var(--color-danger)", cursor: "pointer", padding: 4, fontSize: 14, marginLeft: 8 }} title="Remove Sector">✕</button>
                  </div>
                ))}
              </div>
            </div>

            {/* BPLO Location */}
            <div>
              <div style={{ marginBottom: 12, marginTop: 16 }}>
                <label style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)", display: "block", marginBottom: 8 }}>BPLO Base Station Coordinates</label>
                <div style={{ display: "flex", gap: 10 }}>
                  <button type="button" className="ghost-btn" style={{ padding: "6px 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 6, background: "var(--color-hover)", border: "1px solid var(--color-border)" }} onClick={handleUseCurrentLocation}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="10" r="3" /><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" /></svg>
                    Use My Location
                  </button>
                  <button type="button" className="ghost-btn" style={{ padding: "6px 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 6, background: "var(--color-hover)", border: "1px solid var(--color-border)" }} onClick={() => setShowMapModal(true)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" /></svg>
                    Pick on Map
                  </button>
                </div>
              </div>
              <div style={{ display: "flex", gap: 16 }}>
                <div style={{ flex: 1, background: "var(--color-hover)", padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                  <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "var(--color-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Latitude</label>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-ink)", fontFamily: "monospace" }}>{wlcConfig.bplo_lat || "—"}</div>
                </div>
                <div style={{ flex: 1, background: "var(--color-hover)", padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                  <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "var(--color-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Longitude</label>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-ink)", fontFamily: "monospace" }}>{wlcConfig.bplo_lng || "—"}</div>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
              <button className="primary-btn" type="button" onClick={handleSavePolicy} disabled={savingPolicy}>
                {savingPolicy ? "Saving..." : "Save Policy"}
              </button>
            </div>
          </div>
        </section>

        {/* System Security */}
        <section className="saas-card frosted-glass">
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ margin: "0 0 8px", color: "var(--color-ink)", fontSize: 18 }}>System Security</h3>
            <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13 }}>Manage sign-in protection and admin access controls. Changes here are applied immediately.</p>
          </div>
          <div style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700, color: "var(--color-ink)" }}>Change password</div>
                <div style={{ color: "var(--color-muted)", fontSize: 12 }}>Update your account password with a strong passphrase.</div>
              </div>
              <button className="ghost-btn" type="button" style={{ padding: "8px 12px" }} onClick={() => setShowPasswordModal(true)}>Update</button>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700, color: "var(--color-ink)" }}>Two-factor auth</div>
                <div style={{ color: "var(--color-muted)", fontSize: 12 }}>Protect your account with one-time codes.</div>
              </div>
              <button
                className={user?.is_2fa_enabled ? "ghost-btn" : "primary-btn"}
                type="button"
                style={{ padding: "8px 16px", color: user?.is_2fa_enabled ? "var(--color-danger)" : undefined }}
                onClick={handleToggle2FA}
              >
                {user?.is_2fa_enabled ? "Disable" : "Enable"}
              </button>
            </div>
          </div>
        </section>

        {/* Legal & Support */}
        <section className="saas-card frosted-glass">
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ margin: "0 0 8px", color: "var(--color-ink)", fontSize: 18 }}>Legal & Support</h3>
            <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13 }}>Review the platform's terms of service and privacy policy.</p>
          </div>
          <div style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700, color: "var(--color-ink)" }}>Terms & Conditions</div>
                <div style={{ color: "var(--color-muted)", fontSize: 12 }}>Read the terms of service for using the REVELA platform.</div>
              </div>
              <button type="button" style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, cursor: "pointer", fontSize: 13, padding: "8px 12px" }} onClick={() => setShowTermsDoc(true)}>View</button>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700, color: "var(--color-ink)" }}>Privacy Policy</div>
                <div style={{ color: "var(--color-muted)", fontSize: 12 }}>Understand how your data is collected, used, and protected.</div>
              </div>
              <button type="button" style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, cursor: "pointer", fontSize: 13, padding: "8px 12px" }} onClick={() => setShowPrivacyDoc(true)}>View</button>
            </div>
          </div>
        </section>
      </div>

      <AnimatePresence isVisible={showPasswordModal}>
        <ChangePasswordModal token={token} onClose={() => setShowPasswordModal(false)} />
      </AnimatePresence>
      <AnimatePresence isVisible={show2FAModal}>
        <Setup2FAModal token={token} onClose={() => setShow2FAModal(false)} onSuccess={refreshUser} />
      </AnimatePresence>
      <AnimatePresence isVisible={showTermsDoc}>
        <LegalDocModal title="Terms & Conditions" onClose={() => setShowTermsDoc(false)}>
          <TermsPage />
        </LegalDocModal>
      </AnimatePresence>
      <AnimatePresence isVisible={showPrivacyDoc}>
        <LegalDocModal title="Privacy Policy" onClose={() => setShowPrivacyDoc(false)}>
          <PrivacyPage />
        </LegalDocModal>
      </AnimatePresence>

      {/* Map Picker Modal */}
      <AnimatePresence isVisible={showMapModal}>
        <MapPickerModal
          isLoaded={isLoaded}
          loadError={loadError}
          isDark={isDark}
          center={{ lat: wlcConfig.bplo_lat || 13.9639, lng: wlcConfig.bplo_lng || 121.1114 }}
          marker={wlcConfig.bplo_lat && wlcConfig.bplo_lng ? { lat: wlcConfig.bplo_lat, lng: wlcConfig.bplo_lng } : null}
          onPick={({ lat, lng }) => {
            setWlcConfig(prev => ({ ...prev, bplo_lat: lat, bplo_lng: lng }));
            setShowMapModal(false);
            Swal.fire({
              title: "Base Station Updated",
              text: `Coordinates set to ${lat}, ${lng}. Click Save Changes to persist.`,
              icon: "success",
              timer: 2500,
              showConfirmButton: false,
              toast: true,
              position: "top-end",
            });
          }}
          onClose={() => setShowMapModal(false)}
        />
      </AnimatePresence>

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
      </footer>
    </DashboardLayout>
  );
}
