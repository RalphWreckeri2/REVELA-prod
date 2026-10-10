import { createPortal } from "react-dom";

/**
 * Shown at 9 minutes of inactivity.
 *
 * Deliberately has no close button and no backdrop-dismiss: the only two
 * outcomes are "Stay Logged In" or being logged out one minute later.
 */
export default function InactivityWarningModal({ onStayLoggedIn, onLogout }) {
  return createPortal(
    <div
      className="modal-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        background: "rgba(15, 23, 42, 0.72)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "20px 16px",
      }}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="inactivity-warning-title"
      aria-describedby="inactivity-warning-body"
    >
      <div
        className="modal-panel"
        style={{
          background: "var(--color-modal-bg, #ffffff)",
          borderRadius: "var(--radius-lg, 16px)",
          width: "min(100%, 460px)",
          boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.45)",
          border: "1px solid var(--color-border-soft, rgba(226, 232, 240, 0.6))",
          borderTop: "3px solid var(--color-gold, #eab308)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "28px 28px 8px" }}>
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--color-gold-light, rgba(234, 179, 8, 0.1))",
              border: "1px solid var(--color-gold, #eab308)",
              marginBottom: "16px",
            }}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--color-gold-dark, #ca8a04)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3.2 1.9" />
            </svg>
          </div>

          <h2
            id="inactivity-warning-title"
            style={{
              margin: 0,
              fontSize: "19px",
              fontWeight: 700,
              letterSpacing: "-0.2px",
              color: "var(--color-ink, #1a202c)",
            }}
          >
            Session About to Expire
          </h2>

          <p
            id="inactivity-warning-body"
            style={{
              margin: "10px 0 0",
              fontSize: "14px",
              lineHeight: 1.55,
              color: "var(--color-muted, #64748b)",
            }}
          >
            Your session is about to expire due to inactivity. You will be
            automatically logged out in 1 minute.
          </p>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "10px",
            padding: "20px 28px 26px",
          }}
        >
          <button
            type="button"
            onClick={onLogout}
            style={{
              border: "1px solid var(--color-border, rgba(226,232,240,0.8))",
              background: "var(--color-card-alt, #f8fafc)",
              color: "var(--color-ink, #1a202c)",
              padding: "10px 18px",
              borderRadius: "var(--radius-md, 10px)",
              fontSize: "14px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "background 0.15s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--color-hover, rgba(0,0,0,0.03))";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "var(--color-card-alt, #f8fafc)";
            }}
          >
            Log Out Now
          </button>

          <button
            type="button"
            onClick={onStayLoggedIn}
            autoFocus
            style={{
              border: "1px solid var(--color-primary-dark, #3b6d11)",
              background: "linear-gradient(135deg, var(--color-primary, #56ab2f) 0%, var(--color-primary-dark, #3b6d11) 100%)",
              color: "#ffffff",
              padding: "10px 20px",
              borderRadius: "var(--radius-md, 10px)",
              fontSize: "14px",
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 4px 12px -4px rgba(59, 109, 17, 0.5)",
              transition: "filter 0.15s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.filter = "brightness(1.06)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.filter = "none";
            }}
          >
            Stay Logged In
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}