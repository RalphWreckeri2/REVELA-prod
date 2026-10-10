export default function DesktopAccessRequired() {
  return (
    <main className="desktop-access-required">
      <div className="desktop-access-card">
        <div className="desktop-access-icon" aria-hidden="true">↔</div>
        <p className="desktop-access-eyebrow">REVELA ADMIN PORTAL</p>
        <h1>Desktop Access Required</h1>
        <p>
          The REVELA web dashboard is designed for desktop and laptop browsers.
          Please open it on a computer. Field inspectors can continue using the
          REVELA mobile application.
        </p>
      </div>
    </main>
  );
}
