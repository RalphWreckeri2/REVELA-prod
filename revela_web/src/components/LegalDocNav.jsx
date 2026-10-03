import { useNavigate, useLocation } from "react-router-dom";

/**
 * Shared navigation header for REVELA legal documents.
 * Supports both standalone URL routes (/terms, /privacy, /cookies)
 * and in-app modal views.
 *
 * @param {string} activeDoc - 'terms' | 'privacy' | 'cookies'
 * @param {function} onSwitchDoc - Optional callback when switching tabs inside a modal
 * @param {boolean} isModal - True if rendered inside a modal dialog
 */
export default function LegalDocNav({ activeDoc = "terms", onSwitchDoc, isModal = false }) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleTabClick = (docKey) => {
    if (onSwitchDoc) {
      onSwitchDoc(docKey);
    } else {
      if (docKey === "terms") navigate("/terms");
      else if (docKey === "privacy") navigate("/privacy");
      else if (docKey === "cookies") navigate("/cookies");
    }
  };

  const handlePrint = () => {
    window.print();
  };

  const handleBack = () => {
    // If user has history within the app, go back; otherwise go to root
    if (window.history.length > 1 && location.key !== "default") {
      navigate(-1);
    } else {
      navigate("/");
    }
  };

  return (
    <div className={`legal-doc-nav-wrapper ${isModal ? "is-modal" : "is-standalone"}`}>
      {/* Top action bar shown on standalone pages */}
      {!isModal && (
        <div className="legal-standalone-topbar no-print">
          <button
            type="button"
            className="legal-back-btn"
            onClick={handleBack}
            title="Return to REVELA portal"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
            <span>Back to Portal</span>
          </button>

          <div className="legal-topbar-actions">
            <button
              type="button"
              className="legal-action-pill-btn"
              onClick={handlePrint}
              title="Print or Save as PDF"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 6 2 18 2 18 9" />
                <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
                <rect x="6" y="14" width="12" height="8" />
              </svg>
              <span>Print / Save PDF</span>
            </button>
          </div>
        </div>
      )}

      {/* Pill tabs switcher */}
      <div className="legal-nav-tabs no-print">
        <button
          type="button"
          className={`legal-nav-tab ${activeDoc === "terms" ? "active" : ""}`}
          onClick={() => handleTabClick("terms")}
          aria-current={activeDoc === "terms" ? "page" : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
          <span>Terms &amp; Conditions</span>
        </button>

        <button
          type="button"
          className={`legal-nav-tab ${activeDoc === "privacy" ? "active" : ""}`}
          onClick={() => handleTabClick("privacy")}
          aria-current={activeDoc === "privacy" ? "page" : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          <span>Privacy Policy</span>
        </button>

        <button
          type="button"
          className={`legal-nav-tab ${activeDoc === "cookies" ? "active" : ""}`}
          onClick={() => handleTabClick("cookies")}
          aria-current={activeDoc === "cookies" ? "page" : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <circle cx="8" cy="9" r="1.5" fill="currentColor" />
            <circle cx="15" cy="8" r="1.5" fill="currentColor" />
            <circle cx="10" cy="15" r="1.5" fill="currentColor" />
            <circle cx="16" cy="14" r="1.5" fill="currentColor" />
          </svg>
          <span>Cookie &amp; Storage Policy</span>
        </button>
      </div>
    </div>
  );
}
