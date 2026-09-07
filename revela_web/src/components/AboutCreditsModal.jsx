import React from "react";
import { createPortal } from "react-dom";
import revelaLogo from "../assets/logo.png";
import municipalSeal from "../assets/seal.png";

const TEAM_MEMBERS = [
  {
    name: "Ralph Matthew A. Samonte",
    initials: "RS",
    role: "Project Lead",
    color: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
  },
  {
    name: "Reymark Levitare",
    initials: "RL",
    role: null,
    color: "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)",
  },
  {
    name: "Ruffa Anoya",
    initials: "RA",
    role: null,
    color: "linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)",
  },
];

export default function AboutCreditsModal({ onClose, isClosing }) {
  return createPortal(
    <div
      className={"modal-backdrop" + (isClosing ? " closing" : "")}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(15, 23, 42, 0.65)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "20px 16px",
      }}
      onClick={onClose}
    >
      <div
        className={"modal-panel" + (isClosing ? " closing" : "")}
        style={{
          background: "var(--color-modal-bg, #ffffff)",
          borderRadius: "20px",
          width: "min(100%, 740px)",
          maxHeight: "min(92vh, 840px)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.35)",
          border: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Top Bar */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 24px",
            borderBottom: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
            background: "var(--color-surface, rgba(255, 255, 255, 0.7))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: "var(--color-primary, #10b981)",
                background: "var(--color-primary-light, rgba(16, 185, 129, 0.1))",
                padding: "3px 10px",
                borderRadius: 999,
              }}
            >
              System Information
            </span>
            <span style={{ fontSize: 12, color: "var(--color-muted, #64748b)" }}>
              v1.0.0 Production
            </span>
          </div>
          <button
            className="modal-close-btn"
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--color-muted, #64748b)",
              cursor: "pointer",
              padding: 6,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            title="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px" }}>
          {/* Header Banner */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 20,
              paddingBottom: 24,
              borderBottom: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
              flexWrap: "wrap",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <img
                src={revelaLogo}
                alt="REVELA Logo"
                style={{ width: 56, height: 56, objectFit: "contain", borderRadius: 12 }}
              />
              <img
                src={municipalSeal}
                alt="Municipal Seal"
                style={{ width: 50, height: 50, objectFit: "contain" }}
              />
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <h2
                style={{
                  margin: "0 0 4px",
                  fontSize: 22,
                  fontWeight: 800,
                  color: "var(--color-ink, #0f172a)",
                  letterSpacing: "-0.5px",
                }}
              >
                REVELA
              </h2>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  lineHeight: 1.5,
                  color: "var(--color-muted, #64748b)",
                }}
              >
                Geospatial Business Intelligence &amp; Compliance Monitoring System
              </p>
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--color-primary-dark, #059669)",
                }}
              >
                Municipality of Mataasnakahoy, Batangas — BPLO Deployment
              </div>
            </div>
          </div>

          {/* About REVELA Narrative */}
          <div style={{ marginTop: 24 }}>
            <h3
              style={{
                margin: "0 0 8px",
                fontSize: 14,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--color-ink, #0f172a)",
              }}
            >
              About the Platform
            </h3>
            <p
              style={{
                margin: 0,
                fontSize: 13.5,
                lineHeight: 1.65,
                color: "var(--color-muted, #475569)",
              }}
            >
              REVELA is an enterprise civic intelligence platform designed specifically for the Business
              Permits and Licensing Office (BPLO). It combines geospatial mapping, automated detection
              of unregistered commercial establishments, and synchronized real-time field inspection
              dispatch to streamline local municipal revenue compliance and governance.
            </p>
          </div>

          {/* Core Development Team */}
          <div style={{ marginTop: 28 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 14,
              }}
            >
              <h3
                style={{
                  margin: 0,
                  fontSize: 14,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--color-ink, #0f172a)",
                }}
              >
                Core Development Team
              </h3>
              <span style={{ fontSize: 11, color: "var(--color-muted, #64748b)" }}>
                Authors &amp; Engineers
              </span>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: 14,
              }}
            >
              {TEAM_MEMBERS.map((member) => (
                <div
                  key={member.name}
                  style={{
                    padding: "16px 18px",
                    borderRadius: 14,
                    background: "var(--color-surface-subtle, rgba(248, 250, 252, 0.6))",
                    border: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                  }}
                >
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: "50%",
                      background: member.color,
                      color: "#ffffff",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 15,
                      fontWeight: 700,
                      flexShrink: 0,
                      boxShadow: "0 4px 10px rgba(0, 0, 0, 0.12)",
                    }}
                  >
                    {member.initials}
                  </div>
                  <div>
                    <div
                      style={{
                        fontSize: 14.5,
                        fontWeight: 700,
                        color: "var(--color-ink, #0f172a)",
                        lineHeight: 1.3,
                      }}
                    >
                      {member.name}
                    </div>
                    {member.role && (
                      <div
                        style={{
                          fontSize: 11.5,
                          fontWeight: 600,
                          color: "var(--color-primary, #10b981)",
                          marginTop: 3,
                        }}
                      >
                        {member.role}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Official Notice */}
          <div
            style={{
              marginTop: 28,
              padding: "14px 18px",
              borderRadius: 12,
              background: "var(--color-primary-light, rgba(16, 185, 129, 0.08))",
              border: "1px solid rgba(16, 185, 129, 0.2)",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              style={{ color: "var(--color-primary-dark, #059669)", flexShrink: 0 }}
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--color-ink, #0f172a)" }}>
              Designed and deployed for the <strong>Business Permits &amp; Licensing Office (BPLO)</strong>,
              Municipality of Mataasnakahoy, Province of Batangas.
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "14px 28px",
            borderTop: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
            background: "var(--color-surface, rgba(255, 255, 255, 0.7))",
            fontSize: 12,
            color: "var(--color-muted, #64748b)",
          }}
        >
          <div>&copy; 2026 REVELA. All rights reserved.</div>
          <button className="primary-btn" type="button" onClick={onClose} style={{ padding: "8px 20px" }}>
            Done
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
