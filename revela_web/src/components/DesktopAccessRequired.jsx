import sealImg from "../assets/seal.png";
import "../styles/DesktopAccessRequired.css";

/**
 * Shown on phone-sized screens, where the administrative dashboard is not
 * usable. Styling deliberately reuses the REVELA login page's tokens and
 * treatments (off-white base, topographic grid, green/gold ambient orbs,
 * frosted glass card, forest-green headings) so it reads as part of the same
 * product rather than a generic browser error page.
 */
export default function DesktopAccessRequired() {
  return (
    <main className="restricted-root">
      {/* Decorative layer only. Contained here so the blurred orbs can bleed
          without forcing overflow handling onto the content. */}
      <div className="restricted-backdrop" aria-hidden="true">
        <div className="restricted-topo" />
        <div className="restricted-orb restricted-orb-tl" />
        <div className="restricted-orb restricted-orb-br" />
        <div className="restricted-orb restricted-orb-mid" />
      </div>

      <section className="restricted-card" aria-labelledby="restricted-title">
        <header className="restricted-brand">
          <div className="restricted-seal-row">
            <img src={sealImg} alt="" className="restricted-seal" />
            <span className="restricted-muni">Mataasnakahoy, Batangas</span>
          </div>
          <div className="restricted-gold-bar" />
          <p className="restricted-powered">Powered by</p>
          <h1 className="restricted-wordmark">REVELA</h1>
          <p className="restricted-portal-label">BPLO Admin Portal</p>
        </header>

        <div className="restricted-divider" />

        <div className="restricted-body">
          <div className="restricted-icon" aria-hidden="true">
            <svg viewBox="0 0 48 48" fill="none">
              <rect x="7" y="9" width="34" height="23" rx="2.5" />
              <path d="M4 39h40M19 32v7M29 32v7" />
              <path d="M13 16h13M13 21h9" />
            </svg>
          </div>

          <h2 id="restricted-title" className="restricted-title">
            Best Viewed on a Larger Screen
          </h2>
          <p className="restricted-message">
            The REVELA Admin Portal is designed for tablets, laptops, and
            desktop computers. For the best experience, please open this page
            on a larger device.
          </p>
          <p className="restricted-note">
            Field inspectors can continue using the REVELA mobile application.
          </p>
        </div>
      </section>
    </main>
  );
}