import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useTheme } from "../context/themeContext";
import revelaLogo from "../assets/logo.png";
import municipalMap from "../assets/mkahoybg.png";
import municipalMapDark from "../assets/mkahoybgdark.png";
import TermsPage from "../components/TermsPage";
import PrivacyPage from "../components/PrivacyPage";
import CookiePolicyPage from "../components/CookiePolicyPage";
import AboutCreditsModal from "../components/AboutCreditsModal";
import AnimatePresence from "../components/AnimatePresence";
import DesktopAccessRequired from "../components/DesktopAccessRequired";
import LandingIntroReveal from "../components/LandingIntroReveal";
import LandingRoadHighlight from "../components/LandingRoadHighlight";
import { usePublicPageTransition } from "../context/publicPageTransitionContext";
import { useDeviceAccess } from "../hooks/useDeviceAccess";
import "../styles/LandingPage.css";

const featureCards = [
  {
    title: "Mapped locations",
    description: "Explore business markers and barangay boundaries together to see where follow-up is needed.",
    highlight: "See businesses in their local context.",
    icon: (
      <>
        <path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z" />
        <circle cx="12" cy="10" r="2.5" />
      </>
    ),
  },
  {
    title: "Registry review",
    description: "Compare mapped locations with business records and review possible matches and flagged locations. A flag calls for review; it is not proof of a violation.",
    highlight: "Check records before drawing conclusions.",
    icon: (
      <>
        <path d="M4 5h16v14H4zM8 9h8m-8 4h8m-8 4h5" />
      </>
    ),
  },
  {
    title: "Inspection tracking",
    description: "Assign follow-up inspections and track their progress from assignment through submission and verification.",
    highlight: "Keep field work moving and visible.",
    icon: (
      <>
        <path d="m12 22 1.5-.7C18 19.2 20 15.4 20 10V5l-8-3-8 3v5c0 5.4 2 9.2 6.5 11.3L12 22Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
  },
  {
    title: "Clear priorities",
    description: "Use analytics and explained scoring to compare relative inspection priorities—not to predict guilt or the probability of a violation.",
    highlight: "Plan inspections with clearer context.",
    icon: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 20v-1a6 6 0 0 1 12 0v1H3Zm13-9a3 3 0 1 0-1-5.8M18 14a5 5 0 0 1 3 4.6v1.4h-3" />
      </>
    ),
  },
  {
    title: "Reports & exports",
    description: "Turn monitoring data into shareable reports, charts, and downloadable CSV or PDF files for follow-up work.",
    icon: (
      <>
        <path d="M6 3h9l4 4v14H6zM15 3v5h4M9 12h7m-7 4h7" />
      </>
    ),
  },
];

function MapPinIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}

function StoreIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 10h18l-2-7H5l-2 7Zm1 0v11h16V10M9 21v-7h6v7" />
      <path d="M3 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" />
    </svg>
  );
}

function LandingLegalModal({ title, isClosing, onClose, children }) {
  return createPortal(
    <div
      className={`landing-modal-backdrop modal-backdrop${isClosing ? " closing" : ""}`}
      onClick={onClose}
    >
      <section
        className={`landing-modal modal-panel${isClosing ? " closing" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="landing-modal-header">
          <h2>{title}</h2>
          <button className="modal-close-btn" type="button" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m18 6-12 12M6 6l12 12" />
            </svg>
          </button>
        </header>
        <div className="landing-modal-content">{children}</div>
      </section>
    </div>,
    document.body,
  );
}

export default function LandingPage() {
  const { isDark } = useTheme();
  const { toLogin } = usePublicPageTransition();
  const { restricted } = useDeviceAccess();
  const [activeSection, setActiveSection] = useState("home");
  const [isNavbarCompact, setIsNavbarCompact] = useState(false);
  const [activeModal, setActiveModal] = useState(null);
  const [isBrowserZoomedOut, setIsBrowserZoomedOut] = useState(() => (
    typeof window !== "undefined" &&
    window.outerWidth > 0 &&
    window.innerWidth > window.outerWidth * 1.25
  ));
  const backdrop = isDark ? municipalMapDark : municipalMap;

  useEffect(() => {
    const updateBrowserZoom = () => {
      setIsBrowserZoomedOut(
        window.outerWidth > 0 &&
        window.innerWidth > window.outerWidth * 1.25,
      );
    };

    window.addEventListener("resize", updateBrowserZoom);
    window.visualViewport?.addEventListener("resize", updateBrowserZoom);
    return () => {
      window.removeEventListener("resize", updateBrowserZoom);
      window.visualViewport?.removeEventListener("resize", updateBrowserZoom);
    };
  }, []);

  useEffect(() => {
    if (!activeModal) return undefined;

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setActiveModal(null);
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeModal]);

  useEffect(() => {
    const scroller = document.querySelector(".landing-page");
    if (!scroller) return undefined;

    let previousScrollTop = scroller.scrollTop;
    const handleScroll = () => {
      const currentScrollTop = scroller.scrollTop;
      const scrollDelta = currentScrollTop - previousScrollTop;

      if (currentScrollTop <= 12) {
        setIsNavbarCompact(false);
      } else if (scrollDelta > 3) {
        setIsNavbarCompact(true);
      } else if (scrollDelta < -3) {
        setIsNavbarCompact(false);
      }

      previousScrollTop = currentScrollTop;
    };

    scroller.addEventListener("scroll", handleScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", handleScroll);
  }, []);

  const switchLegalDocument = (documentKey) => setActiveModal(documentKey);
  const closeModal = () => setActiveModal(null);
  const goHome = (event) => {
    event.preventDefault();
    setActiveSection("home");
    document.querySelector(".landing-page")?.scrollTo({
      top: 0,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  };

  if (restricted || isBrowserZoomedOut) {
    return <DesktopAccessRequired mode="landing" />;
  }

  return (
    <LandingIntroReveal>
    <div
      id="landing-top"
      className="landing-page"
      data-theme={isDark ? "dark" : "light"}
      style={{ "--landing-backdrop": `url("${backdrop}")` }}
    >
      <a className="landing-skip-link" href="#landing-main">Skip to content</a>

      <header className={`landing-header${isNavbarCompact ? " is-compact" : ""}`}>
        <div className="landing-header-inner">
          <a
            className="landing-brand"
            href="#landing-top"
            aria-label="REVELA home"
             onClick={goHome}
          >
            <img className="landing-brand-mark" src={revelaLogo} alt="" />
            <span>REVELA</span>
          </a>

          <nav className="landing-nav" aria-label="Main navigation">
            {[
              ["home", "Home", "#landing-top"],
              ["about", "About", "#about"],
              ["features", "Features", "#features"],
               ["contact", "Support", "#contact"],
            ].map(([id, label, href]) => (
              <a
                key={id}
                href={href}
                className={activeSection === id ? "is-active" : ""}
                aria-current={activeSection === id ? "page" : undefined}
                 onClick={id === "home" ? goHome : () => setActiveSection(id)}
              >
                {label}
              </a>
            ))}
          </nav>

           <Link className="landing-header-login" to="/login" onClick={toLogin}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="8" r="3.5" />
              <path d="M5 21v-2a7 7 0 0 1 14 0v2H5Z" />
            </svg>
            Log In
          </Link>
        </div>
      </header>

      <div className="landing-page-content">
        <LandingRoadHighlight />
        <main id="landing-main" tabIndex={-1}>
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-hero-inner">
            <div className="landing-intro">
              <p className="landing-eyebrow">
                <MapPinIcon />
                MATAASNAKAHOY, BATANGAS
              </p>
              <h1 id="landing-title">
                <span>Local insight.</span>
                <span>Clearer decisions.</span>
              </h1>
              <p className="landing-description">
                Supporting local business monitoring through location-based insights.
              </p>
               <Link className="landing-login landing-login--primary" to="/login" onClick={toLogin}>
                Log In
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M5 12h14m-6-6 6 6-6 6" />
                </svg>
              </Link>
            </div>

            <div className="landing-map-callout" aria-hidden="true">
              <span className="landing-map-callout-icon"><StoreIcon /></span>
              <span className="landing-map-callout-copy">
                <strong>Local Business</strong>
                <small>Mataasnakahoy, Batangas</small>
              </span>
              <span className="landing-map-callout-arrow">›</span>
            </div>
            <div className="landing-map-pin" aria-hidden="true"><MapPinIcon /></div>
            <div className="landing-compass" aria-hidden="true">
              <span>▲</span>
              <small>N</small>
            </div>

            <div className="landing-highlights" aria-label="REVELA highlights">
               {featureCards.filter((card) => card.highlight).map(({ title, highlight, icon }) => (
                <article className="landing-highlight" key={title}>
                  <span className="landing-highlight-icon">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">{icon}</svg>
                  </span>
                  <h2>{title}</h2>
                  <p>{highlight}</p>
                </article>
              ))}
            </div>
            <a className="landing-hero-feature-link" href="#features" onClick={() => setActiveSection("features")}>
              See all features <span aria-hidden="true">↓</span>
            </a>
          </div>
        </section>

         <section id="about" className="landing-content-section" aria-labelledby="about-title">
           <div className="landing-section-inner">
             <div className="landing-section-lead">
               <p className="landing-section-kicker">ABOUT REVELA</p>
               <h2 id="about-title">A clearer view of local business activity.</h2>
               <p>Built for business monitoring and inspection support in Mataasnakahoy, Batangas.</p>
             </div>
             <div className="landing-section-detail">
               <span className="landing-detail-rule" aria-hidden="true" />
               <p>REVELA brings business records, mapped locations, review flags, and inspection information into one working view. It helps authorized personnel connect what is on the map with what is in the registry and decide where to focus follow-up work.</p>
               <p>Operational priorities help organize inspections; the underlying records and field findings still need human review.</p>
             </div>
           </div>
         </section>

         <section id="features" className="landing-content-section landing-content-section--alternate" aria-labelledby="features-title">
           <div className="landing-section-inner">
             <div className="landing-section-lead">
               <p className="landing-section-kicker">WHAT YOU CAN DO</p>
               <h2 id="features-title">From map to next steps.</h2>
             </div>
             <p className="landing-section-summary">Explore the area, verify records, coordinate inspections, and share the results—all in one workflow.</p>
             <div className="landing-feature-grid">
              {featureCards.map(({ title, description, icon }) => (
                <article className="landing-feature-card" key={title}>
                  <span className="landing-highlight-icon">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">{icon}</svg>
                  </span>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

         <section id="contact" className="landing-content-section" aria-labelledby="contact-title">
           <div className="landing-section-inner">
             <div className="landing-section-lead">
               <p className="landing-section-kicker">ACCESS & SUPPORT</p>
               <h2 id="contact-title">Get the help you need.</h2>
               <p>REVELA is for authorized users. Sign in with your assigned account to access the portal.</p>
               <Link className="landing-login landing-login--primary" to="/login" onClick={toLogin}>Log In <span aria-hidden="true">→</span></Link>
             </div>
             <div className="landing-section-detail landing-support-detail">
               <span className="landing-detail-rule" aria-hidden="true" />
               <h3>Questions about access?</h3>
               <p>Contact your designated system administrator for account assistance. For policy or technical inquiries, the project’s published BPLO contact is <a href="mailto:mkahoy.bplo@gmail.com">mkahoy.bplo@gmail.com</a>.</p>
             </div>
          </div>

          <footer className="landing-footer">
            <div className="landing-footer-inner">
              <span className="landing-footer-brand">REVELA <span aria-hidden="true">·</span> MATAASNAKAHOY, BATANGAS</span>
              <nav className="landing-legal" aria-label="Legal information">
                <button type="button" className="landing-legal-link" onClick={() => setActiveModal("terms")}>Terms &amp; Conditions</button>
                <button type="button" className="landing-legal-link" onClick={() => setActiveModal("privacy")}>Privacy Policy</button>
                <button type="button" className="landing-legal-link" onClick={() => setActiveModal("cookies")}>Cookie Policy</button>
                <button type="button" className="landing-legal-link" onClick={() => setActiveModal("credits")}>Credits</button>
              </nav>
            </div>
          </footer>
        </section>
        </main>
      </div>

      <AnimatePresence isVisible={activeModal === "terms"}>
        <LandingLegalModal title="Terms & Conditions" onClose={closeModal}>
          <TermsPage onSwitchDoc={switchLegalDocument} isModal />
        </LandingLegalModal>
      </AnimatePresence>
      <AnimatePresence isVisible={activeModal === "privacy"}>
        <LandingLegalModal title="Privacy Policy" onClose={closeModal}>
          <PrivacyPage onSwitchDoc={switchLegalDocument} isModal />
        </LandingLegalModal>
      </AnimatePresence>
      <AnimatePresence isVisible={activeModal === "cookies"}>
        <LandingLegalModal title="Cookie & Storage Policy" onClose={closeModal}>
          <CookiePolicyPage onSwitchDoc={switchLegalDocument} isModal />
        </LandingLegalModal>
      </AnimatePresence>
      <AnimatePresence isVisible={activeModal === "credits"}>
        <AboutCreditsModal onClose={closeModal} />
      </AnimatePresence>
    </div>
    </LandingIntroReveal>
  );
}
