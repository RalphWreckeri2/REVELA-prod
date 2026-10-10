export default function DesktopAccessRequired() {
  return (
    <main className="desktop-access-required">
      <div className="desktop-access-card">
        <div className="desktop-access-icon" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <rect x="5" y="6" width="22" height="16" rx="2" />
            <path d="M3 26h26M12 22v4m8-4v4" />
          </svg>
        </div>
        <p className="desktop-access-eyebrow">REVELA ADMIN PORTAL</p>
        <h1>Desktop Access Required</h1>
        <p className="desktop-access-message">
          The REVELA web dashboard is not available on phones. Please use a
          desktop or laptop browser. Tablets may access the dashboard, though a
          desktop or laptop is recommended.
        </p>
        <p className="desktop-access-mobile-note">
          Field inspectors can continue using the REVELA mobile app.
        </p>
      </div>
    </main>
  );
}
