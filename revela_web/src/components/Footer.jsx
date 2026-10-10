/**
 * Footer.jsx
 *
 * Shared authenticated-page footer. Reused by every page so the copyright line
 * and the legal/credits links stay identical across the app.
 *
 * The layout itself lives in CSS (`.saas-footer`): `.saas-content` is a
 * full-height flex column and `.saas-footer { margin-top: auto }`, so the footer
 * is pinned to the bottom of the viewport when a page is short and simply flows
 * after the content when it is tall.
 *
 * Usage: <Footer />
 */

export default function Footer({ className = "", style }) {
  return (
    <footer className={`saas-footer frosted-glass${className ? ` ${className}` : ""}`} style={style}>
      <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
      <p className="footer-links">
        <span>BPLO Portal</span> &bull; <span>System Settings</span> &bull;{" "}
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent("revela:open-about"))}
        >
          About &amp; Credits
        </button>
      </p>
    </footer>
  );
}
