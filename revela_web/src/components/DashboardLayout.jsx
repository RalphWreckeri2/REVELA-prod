/**
 * DashboardLayout.jsx
 *
 * Reusable shell for every authenticated page.
 * Contains: Sidebar + Top Navbar + ambient background.
 * Usage:
 *   <DashboardLayout user={{ initials: "JD", name: "J. Dela Cruz" }}>
 *     <HomePage />
 *   </DashboardLayout>
 *
 * Props:
 *   children  — page content rendered inside .saas-content
 *   user      — { initials: string, name: string }
 *   logo      — imported logo asset (optional)
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  getNotificationsRequest,
  getNotificationsUnreadCountRequest,
  markNotificationsReadRequest,
  deleteNotificationsRequest,
  getNotificationStreamUrl,
} from "../services/api";
import "../styles/global.css";
import Swal from "sweetalert2";
import myLogo from "../assets/logo.png";
import ProfileModal from "../pages/ProfileModal";

// ── Nav config — add new pages here, never touch the layout ──
const NAV_ITEMS = [
  {
    group: "Main",
    items: [
      {
        label: "Overview",
        path: "/home",
        href: "/home",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </svg>
        ),
      },
      {
        label: "Map & Flags",
        path: "/map",
        href: "/map",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="10" r="3" />
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
          </svg>
        ),
      },
      {
        label: "Registry",
        path: "/registry",
        href: "/registry",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        ),
      },
      {
        label: "Analytics",
        path: "/analytics",
        href: "/analytics",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
        ),
      },
      {
        label: "Inspections",
        path: "/inspections",
        href: "/inspections",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 11l3 3L22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </svg>
        ),
      },
    ],
  },
  {
    group: "Management",
    items: [
      {
        label: "User Management",
        path: "/users",
        href: "/users",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        ),
      },
      {
        label: "Export Reports",
        path: "/reports",
        href: "/reports",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        ),
      },
    ],
  },
  {
    group: "System",
    items: [
      {
        label: "Settings",
        path: "/settings",
        href: "/settings",
        icon: (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M19.07 19.07l-1.41-1.41M4.93 19.07l1.41-1.41M12 2v2M12 20v2M2 12h2M20 12h2" />
          </svg>
        ),
      },
    ],
  },
];

// ── Sub-components (private to this file) ──────────────────

function NavBadge({ variant = "red", count }) {
  return <span className={`badge badge--${variant}`}>{count}</span>;
}

function Sidebar({ onLogout }) {
  const location = useLocation();

  return (
    <aside className="saas-sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="brand-logo">
          <img src={myLogo} alt="REVELA Logo" className="logo-img" />
        </div>
        <h2>REVELA</h2>
      </div>

      {/* Nav groups */}
      <div className="sidebar-scroll">
        {NAV_ITEMS.map(({ group, items }, gi) => (
          <div key={group}>
            {gi > 0 && <div className="menu-divider" />}
            <span className="menu-group-label">{group}</span>

            {items.map(({ label, href, path, badge, icon }) => {
              const isActive = path && location.pathname === path;
              return path ? (
                <Link
                  key={label}
                  to={path}
                  className={`menu-item${isActive ? " active" : ""}`}
                >
                  {icon}
                  {label}
                  {badge && <NavBadge variant={badge.variant} count={badge.count} />}
                </Link>
              ) : (
                <a key={label} href={href} className="menu-item">
                  {icon}
                  {label}
                  {badge && <NavBadge variant={badge.variant} count={badge.count} />}
                </a>
              );
            })}
          </div>
        ))}
      </div>

      {/* Logout */}
      <div className="sidebar-footer">
        <button className="logout-btn" onClick={onLogout}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Logout
        </button>
      </div>
    </aside>
  );
}

function formatTimeAgo(iso) {
  if (!iso) return "";
  const str = String(iso).trim();
  // If the timestamp doesn't specify timezone or Z, treat it as UTC from MySQL
  const normalizedIso = str.endsWith("Z") || str.includes("+") ? str : `${str.replace(" ", "T")}Z`;
  const t = new Date(normalizedIso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function TopNavbar({ user = { initials: "JD", name: "J. Dela Cruz" }, searchPlaceholder = "Search businesses, barangays...", onProfileClick }) {
  const { token, user: authUser } = useAuth();
  const [showNotifications, setShowNotifications] = useState(false);
  const notificationButtonRef = useRef(null);
  const notificationPopoverRef = useRef(null);
  const navigate = useNavigate();

  const isAdmin = authUser?.role === "Admin" || authUser?.role === "SUPER_ADMIN" || authUser?.role === "System Administrator";
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isLiveConnected, setIsLiveConnected] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState(() => new Date());
  const [showSnippet, setShowSnippet] = useState(false);
  const lastAlertIdRef = useRef(null);
  const snippetTimerRef = useRef(null);

  const refreshNotifications = useCallback(async () => {
    if (!token || !isAdmin) return;
    try {
      const [listRes, countRes] = await Promise.all([
        getNotificationsRequest(token),
        getNotificationsUnreadCountRequest(token),
      ]);
      setNotifications(listRes?.data ?? []);
      setUnreadCount(countRes?.count ?? 0);
      setLastSyncTime(new Date());
    } catch {
      /* ignore */
    }
  }, [token, isAdmin]);

  const handleGlobalSync = useCallback(async () => {
    setIsSyncing(true);
    try {
      await refreshNotifications();
      window.dispatchEvent(new CustomEvent("revela:global-refresh", { detail: { timestamp: Date.now() } }));
      setLastSyncTime(new Date());
    } finally {
      setTimeout(() => setIsSyncing(false), 600);
    }
  }, [refreshNotifications]);

  useEffect(() => {
    if (!token || !isAdmin) return undefined;
    refreshNotifications();

    let es = null;
    let reconnectTimeout = null;
    let isSubscribed = true;

    const connectSSE = () => {
      if (!isSubscribed) return;
      try {
        es = new EventSource(getNotificationStreamUrl(token));
        
        es.onopen = () => {
          if (!isSubscribed) return;
          setIsLiveConnected(true);
        };

        es.onmessage = (event) => {
          if (!isSubscribed) return;
          let data;
          try {
            data = JSON.parse(event.data);
          } catch {
            return;
          }
          if (data.type === "heartbeat" || data.type === "connected") {
            setIsLiveConnected(true);
            return;
          }
          setIsLiveConnected(true);
          setLastSyncTime(new Date());

          if (data.type !== "detection_progress") {
            refreshNotifications();
          }

          if (data.type === "inspection_submitted" || data.type === "inspection_updated") {
            window.dispatchEvent(
              new CustomEvent("revela:inspection-update", { detail: data }),
            );
          } else if (data.type === "yellow_flag_reported") {
            window.dispatchEvent(
              new CustomEvent("revela:yellow-flag", { detail: data }),
            );
          } else if (data.type === "flag_updated" || data.type === "flag_deleted") {
            window.dispatchEvent(
              new CustomEvent("revela:flag-update", { detail: data }),
            );
          } else if (data.type === "detection_progress") {
            window.dispatchEvent(
              new CustomEvent("revela:detection-progress", { detail: data }),
            );
          } else if (data.type === "registry_progress") {
            window.dispatchEvent(
              new CustomEvent("revela:registry-progress", { detail: data }),
            );
          } else if (data.type === "registry_updated") {
            window.dispatchEvent(
              new CustomEvent("revela:registry-update", { detail: data }),
            );
          } else if (data.type === "password_reset_requested") {
            window.dispatchEvent(
              new CustomEvent("revela:password-reset", { detail: data }),
            );
          } else if (data.type === "user_updated") {
            window.dispatchEvent(
              new CustomEvent("revela:user-update", { detail: data }),
            );
          }
        };

        es.onerror = () => {
          if (!isSubscribed) return;
          setIsLiveConnected(false);
          try {
            es.close();
          } catch {
            /* ignore */
          }
          // Reconnect with 4s backoff
          reconnectTimeout = setTimeout(connectSSE, 4000);
        };
      } catch {
        setIsLiveConnected(false);
        reconnectTimeout = setTimeout(connectSSE, 6000);
      }
    };

    connectSSE();

    // Fallback polling every 20s
    const poll = window.setInterval(() => {
      refreshNotifications();
    }, 20000);

    return () => {
      isSubscribed = false;
      window.clearInterval(poll);
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (es) {
        try {
          es.close();
        } catch {
          /* ignore */
        }
      }
    };
  }, [token, isAdmin, refreshNotifications]);

  useEffect(() => {
    if (!isAdmin || notifications.length === 0 || unreadCount === 0) {
      setShowSnippet(false);
      return;
    }
    const latest = notifications[0];
    if (latest && !latest.readAt && latest.id !== lastAlertIdRef.current) {
      lastAlertIdRef.current = latest.id;
      setShowSnippet(true);

      if (snippetTimerRef.current) clearTimeout(snippetTimerRef.current);
      snippetTimerRef.current = setTimeout(() => {
        setShowSnippet(false);
      }, 7000);
    }
  }, [notifications, unreadCount, isAdmin]);

  useEffect(() => {
    return () => {
      if (snippetTimerRef.current) clearTimeout(snippetTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        showNotifications &&
        notificationPopoverRef.current &&
        !notificationPopoverRef.current.contains(event.target) &&
        notificationButtonRef.current &&
        !notificationButtonRef.current.contains(event.target)
      ) {
        setShowNotifications(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showNotifications]);

  const toggleNotifications = async () => {
    const next = !showNotifications;
    setShowNotifications(next);
    setShowSnippet(false);
    if (snippetTimerRef.current) clearTimeout(snippetTimerRef.current);
    if (next && isAdmin && token) {
      await refreshNotifications();
    }
  };

  const handleMarkAllAsRead = async (e) => {
    if (e) e.stopPropagation();
    setUnreadCount(0);
    setNotifications((prev) =>
      prev.map((n) => ({ ...n, readAt: n.readAt || new Date().toISOString() }))
    );
    if (token) {
      try {
        await markNotificationsReadRequest(token);
      } catch (err) {
        console.error("Failed to mark all as read", err);
      }
    }
  };

  const handleClearAll = async (e) => {
    if (e) e.stopPropagation();
    setNotifications([]);
    setUnreadCount(0);
    if (token) {
      try {
        await deleteNotificationsRequest(token);
      } catch (err) {
        console.error("Failed to delete notifications", err);
      }
    }
  };

  const handleNotificationClick = async (note) => {
    if (!note.readAt && token) {
      try {
        markNotificationsReadRequest(token, [note.id]).catch(() => {});
        setNotifications((prev) =>
          prev.map((n) => (n.id === note.id ? { ...n, readAt: new Date().toISOString() } : n))
        );
        setUnreadCount((c) => Math.max(0, c - 1));
      } catch {
        /* ignore */
      }
    }
    if (note.link) navigate(note.link);
    setShowNotifications(false);
  };

  return (
    <header className="top-navbar frosted-glass">
      <style>{`
        @keyframes snippetBounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        @keyframes snippetPulse {
          0% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(0.9); }
          100% { opacity: 1; transform: scale(1); }
        }
      `}</style>

      {/*<div className="search-bar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input type="text" placeholder={searchPlaceholder} />
      </div>*/}

      <div className="top-nav-right" style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        {/* Live sync pill badge */}
        <div
          className="live-sync-badge"
          title={`Server Sync Status: ${isLiveConnected ? "Connected (Real-time SSE active)" : "Polling (Auto-reconnecting)"}`}
        >
          <span className={`live-dot ${isLiveConnected ? "" : "live-dot--offline"}`} />
          <span>{isLiveConnected ? "Live Sync" : "Syncing…"}</span>
        </div>

        {/* Instant manual sync button */}
        <button
          className="quick-refresh-icon-btn"
          type="button"
          aria-label="Refresh Data"
          title="Refresh All Data (In-Place)"
          onClick={handleGlobalSync}
          disabled={isSyncing}
        >
          <svg
            className={isSyncing ? "spin-icon" : ""}
            viewBox="0 0 24 24"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" />
          </svg>
        </button>

        <div className="notification-wrapper" style={{ position: "relative" }}>
          <button
            ref={notificationButtonRef}
            className="icon-btn"
            type="button"
            aria-label="Notifications"
            aria-expanded={showNotifications}
            onClick={toggleNotifications}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            {isAdmin && unreadCount > 0 ? (
              <span className="nav-badge" title={`${unreadCount} unread`} />
            ) : null}
          </button>

          {isAdmin && unreadCount > 0 && showSnippet && !showNotifications && notifications.length > 0 && (
            <div 
              onClick={toggleNotifications}
              style={{
                position: "absolute",
                top: "calc(100% + 14px)",
                right: "-6px",
                background: "var(--color-primary)",
                color: "#fff",
                padding: "10px 14px",
                borderRadius: "var(--radius-md)",
                boxShadow: "0 10px 25px rgba(86,171,47,0.35)",
                cursor: "pointer",
                zIndex: 90,
                animation: "snippetBounce 3s ease-in-out infinite",
                border: "1px solid rgba(255,255,255,0.2)",
                minWidth: "max-content",
                maxWidth: "280px"
              }}
            >
              {/* Pointer triangle */}
              <div style={{
                position: "absolute",
                top: "-6px",
                right: "18px",
                width: 0,
                height: 0,
                borderLeft: "6px solid transparent",
                borderRight: "6px solid transparent",
                borderBottom: "6px solid var(--color-primary)"
              }}></div>
              
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em", opacity: 0.9, fontWeight: 700 }}>
                  {unreadCount} New Alert{unreadCount > 1 ? 's' : ''}
                </div>
                <button
                  type="button"
                  aria-label="Dismiss alert popup"
                  title="Dismiss"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "rgba(255,255,255,0.85)",
                    cursor: "pointer",
                    fontSize: "11px",
                    lineHeight: 1,
                    padding: "2px 4px",
                    marginLeft: "8px",
                    borderRadius: "3px"
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowSnippet(false);
                    if (snippetTimerRef.current) clearTimeout(snippetTimerRef.current);
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.color = "#fff"}
                  onMouseLeave={(e) => e.currentTarget.style.color = "rgba(255,255,255,0.85)"}
                >
                  ✕
                </button>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--color-modal-bg)", display: "inline-block", animation: "snippetPulse 2s infinite", flexShrink: 0 }}></span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {notifications[0].title}
                </span>
              </div>
            </div>
          )}

          {showNotifications && (
            <div className="notification-popover" ref={notificationPopoverRef}>
              <div className="notification-popover__header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>Notifications</span>
                <div style={{ display: "flex", gap: 4, marginTop: -2 }}>
                  <button 
                    title="Mark all as read"
                    style={{ background: "transparent", border: "none", color: "var(--color-primary)", cursor: "pointer", padding: "6px", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", transition: "background 0.2s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "rgba(52, 211, 153, 0.15)"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    onClick={handleMarkAllAsRead}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M18 6 7 17l-5-5"></path>
                      <path d="m22 10-7.5 7.5L13 16"></path>
                    </svg>
                  </button>
                  <button 
                    title="Clear all"
                    style={{ background: "transparent", border: "none", color: "var(--color-muted)", cursor: "pointer", padding: "6px", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", transition: "background 0.2s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "var(--color-hover)"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    onClick={handleClearAll}
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 6h18"></path>
                      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
                      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path>
                    </svg>
                  </button>
                </div>
              </div>
              <div className="notification-list" style={{ maxHeight: "560px", overflowY: "auto", overscrollBehavior: "contain" }}>
                {!isAdmin && (
                  <div className="notification-item">
                    <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13 }}>
                      In-app alerts are available for administrators.
                    </p>
                  </div>
                )}
                {isAdmin && notifications.length === 0 && (
                  <div style={{ padding: "40px 20px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 16 }}>
                    <img src="/searching.png" alt="No notifications" style={{ height: 100, objectFit: "contain", opacity: 0.9 }} />
                    <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13, maxWidth: 220 }}>
                      No notifications yet. You will be alerted when an inspector submits evidence for review.
                    </p>
                  </div>
                )}
                {isAdmin &&
                  notifications.map((note) => {
                    const isUnread = !note.readAt;
                    return (
                      <div
                        key={note.id}
                        className={`notification-item ${isUnread ? "notification-item--unread" : ""}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => handleNotificationClick(note)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            handleNotificationClick(note);
                          }
                        }}
                        style={{
                          cursor: note.link ? "pointer" : "default",
                          position: "relative",
                          background: isUnread ? "rgba(52, 211, 153, 0.05)" : "transparent",
                          borderColor: isUnread ? "rgba(52, 211, 153, 0.25)" : "var(--color-border-soft)"
                        }}
                      >
                        {isUnread && (
                          <span
                            style={{
                              position: "absolute",
                              top: 14,
                              right: 14,
                              width: 8,
                              height: 8,
                              borderRadius: "50%",
                              background: "var(--color-primary)",
                              boxShadow: "0 0 8px var(--color-primary)",
                              display: "block"
                            }}
                            title="Unread"
                          />
                        )}
                        <div className="notification-item-icon" style={{
                          background: isUnread ? "rgba(52, 211, 153, 0.22)" : "rgba(52, 211, 153, 0.12)"
                        }}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                          </svg>
                        </div>
                        <div className="notification-item-content">
                          <strong style={{ color: isUnread ? "var(--color-ink)" : "var(--color-muted)", fontWeight: isUnread ? 700 : 600 }}>{note.title}</strong>
                          <p>{note.body}</p>
                          <span>{formatTimeAgo(note.createdAt)}</span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
        </div>

        <button
          className="nav-profile"
          type="button"
          onClick={onProfileClick}
        >
          <div className="nav-avatar">{user.initials}</div>
          <div className="nav-user-info">
            <span className="welcome-text">Welcome</span>
            <span className="user-name">{user.name} ▾</span>
          </div>
        </button>
      </div>
    </header>
  );
}

// ── Public export ──────────────────────────────────────────

/**
 * @param {{ children: React.ReactNode, user?: object, onLogout?: () => void }} props
 */
export default function DashboardLayout({ children, onLogout }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const navigate = useNavigate();
  const { user: authUser, logout } = useAuth();

  const handleLogout = () => {
    Swal.fire({
      title: 'Are you sure?',
      text: "You will be logged out of the system.",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtoncolor: "var(--color-muted)",
      confirmButtonText: 'Yes, log out'
    }).then((result) => {
      if (result.isConfirmed) {
        if (typeof onLogout === "function") {
          onLogout();
        } else if (logout) {
          logout();
        }
        navigate("/");
      }
    });
  };

  const displayUser = {
    initials: authUser?.fullName 
      ? authUser.fullName.split(" ").map(n => n[0]).join("").substring(0, 2).toUpperCase() 
      : "?",
    name: authUser?.fullName || "Unknown User"
  };

  return (
    <div className={`saas-root ${isMobileMenuOpen ? "mobile-open" : ""}`}>
      
      <button 
        className="mobile-toggle" 
        onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
      >

        {isMobileMenuOpen ? "✕" : "☰"}
      
      </button>
      <Sidebar onLogout={handleLogout} />

      <div className="saas-main">
        <div className="ambient-bg-mesh" />
        <TopNavbar user={displayUser} onProfileClick={() => setShowProfileModal(true)} />

        {/* Each page owns its .saas-content padding via this wrapper */}
        <main className="saas-content">
          {children}
        </main>
      </div>

      {showProfileModal && <ProfileModal onClose={() => setShowProfileModal(false)} />}
    </div>
  );
}
