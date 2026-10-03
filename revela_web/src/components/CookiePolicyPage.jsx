import LegalDocNav from "./LegalDocNav";
import "../styles/global.css";

/**
 * Cookie and Web Storage Policy for the REVELA platform.
 * Supports standalone route rendering (/cookies) and in-modal rendering.
 */
export default function CookiePolicyPage({ onSwitchDoc, isModal = false }) {
  return (
    <div className={`legal-page-container ${isModal ? "legal-page-container--modal" : ""}`}>
      <div className="legal-page-content">
        <LegalDocNav activeDoc="cookies" onSwitchDoc={onSwitchDoc} isModal={isModal} />

        <span className="legal-page-eyebrow">Mataasnakahoy BPLO &bull; Legal &amp; Governance</span>
        <h1>Cookie &amp; Web Storage Policy</h1>
        <div className="legal-page-divider" />
        <p className="legal-page-subtitle">
          Last Updated: October 2026 &bull; Compliant with RA 10173 (Data Privacy Act of 2012)
        </p>

        <p>
          This Cookie &amp; Web Storage Policy explains how the Municipality of Mataasnakahoy
          ("we," "us," or "our"), through its Business Permits and Licensing Office (BPLO),
          utilizes cookies, HTML5 local storage, session storage, and related device storage
          mechanisms in connection with the REVELA geospatial intelligence and field inspection
          platform. This policy covers both the REVELA administrative web dashboard ("Web Portal")
          and the REVELA field inspection mobile application ("Mobile App").
        </p>

        <div className="legal-page-notice">
          <p>
            Official Government Platform Notice: REVELA is an internal municipal system
            restricted to authorized personnel of the Municipality of Mataasnakahoy. We do not
            serve commercial advertisements, employ marketing tracking pixels, or monetize user data.
          </p>
        </div>

        <h2>1. Understanding Cookies &amp; Web Storage</h2>
        <p>
          To maintain high performance, responsive user interfaces, and robust multi-factor session
          security, modern web applications utilize local client-side storage technologies:
        </p>
        <ul>
          <li>
            <strong>HTTP Cookies:</strong> Small text files placed on your browser or device by web
            servers. Cookies can be "session" cookies (which expire when you close your browser) or
            "persistent" cookies (which remain stored until an expiration date or until manually cleared).
          </li>
          <li>
            <strong>HTML5 Web Storage (Local &amp; Session Storage):</strong> A modern, secure web
            standard allowing web applications to store structured key-value data directly in the
            client's browser. Unlike traditional cookies, local storage data is never automatically
            transmitted over the network on every HTTP request, significantly reducing attack surfaces
            and bandwidth consumption.
          </li>
          <li>
            <strong>Mobile Device Storage:</strong> Native key-value stores (such as Android
            SharedPreferences and iOS UserDefaults/Keychain) used by the REVELA Mobile App to retain
            offline task queues, UI preferences, and local cryptographic tokens.
          </li>
        </ul>

        <h2>2. Our "No Commercial Tracking" Guarantee</h2>
        <p>
          As an official regulatory instrument of the Local Government Unit (LGU) of Mataasnakahoy:
        </p>
        <ul>
          <li>We <strong>NEVER</strong> use advertising, targeting, or commercial profiling cookies.</li>
          <li>We <strong>NEVER</strong> share, sell, or rent your session or device data to marketing data brokers.</li>
          <li>We <strong>NEVER</strong> employ third-party behavioral analytics or ad-retargeting pixels (e.g., Meta Pixel, TikTok, or commercial marketing SDKs).</li>
        </ul>

        <h2>3. Detailed Inventory of Storage &amp; Cookies Used</h2>
        <p>
          The table below itemizes every local storage key and third-party technical cookie employed
          within the REVELA platform:
        </p>

        <div className="legal-table-wrapper">
          <table className="legal-table">
            <thead>
              <tr>
                <th style={{ width: "24%" }}>Storage Key / Name</th>
                <th style={{ width: "18%" }}>Technology</th>
                <th style={{ width: "18%" }}>Classification</th>
                <th>Purpose &amp; Retention</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <code>revela_token</code>
                </td>
                <td>HTML5 LocalStorage</td>
                <td>
                  <span className="legal-badge legal-badge--essential">Strictly Necessary</span>
                </td>
                <td>
                  Stores the cryptographic JSON Web Token (JWT) issued upon successful multi-factor
                  authentication. Required to authorize your administrative requests across protected
                  dashboard endpoints. Automatically wiped upon clicking "Sign Out" or when session
                  expires.
                </td>
              </tr>
              <tr>
                <td>
                  <code>revela-theme</code>
                </td>
                <td>HTML5 LocalStorage</td>
                <td>
                  <span className="legal-badge legal-badge--functional">Functional Preference</span>
                </td>
                <td>
                  Remembers your active visual display preference (<code>light</code>, <code>dark</code>,
                  or <code>system</code> synchronized). Prevents display flickering and preserves
                  accessibility settings across page reloads.
                </td>
              </tr>
              <tr>
                <td>
                  <code>Google Maps Platform</code>
                </td>
                <td>Third-Party Cookies &amp; Cache</td>
                <td>
                  <span className="legal-badge legal-badge--essential">Essential Service</span>
                </td>
                <td>
                  Utilized by the Google Maps JavaScript API (<code>@react-google-maps/api</code>)
                  to render high-resolution satellite imagery, topographic maps, municipal zoning layers,
                  and geocoding results. Governed under the{" "}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="legal-link"
                  >
                    Google Privacy Policy
                  </a>.
                </td>
              </tr>
              <tr>
                <td>
                  <code>Tour &amp; Walkthrough Flags</code>
                </td>
                <td>HTML5 LocalStorage &amp; Mobile Prefs</td>
                <td>
                  <span className="legal-badge legal-badge--functional">Functional Preference</span>
                </td>
                <td>
                  Records whether guided onboarding tours (Map, Dashboard, Tasks, Settings) have been
                  viewed or dismissed by the user to avoid unnecessary repetition during daily inspections.
                </td>
              </tr>
              <tr>
                <td>
                  <code>Offline Task Queue</code>
                </td>
                <td>Mobile Device Storage</td>
                <td>
                  <span className="legal-badge legal-badge--essential">Strictly Necessary</span>
                </td>
                <td>
                  In the REVELA Mobile App, stores inspection reports, geotags, and photographic evidence
                  locally when field inspectors operate in areas with intermittent cellular connectivity,
                  syncing to the municipal server once connection is restored.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <h2>4. Mobile Device Security &amp; Biometric Integrity</h2>
        <p>
          The REVELA Mobile App supports biometric unlock (fingerprint and facial recognition)
          for field personnel on supported Android and iOS devices. We explicitly confirm:
        </p>
        <ul>
          <li>
            <strong>Biometric Data Never Leaves Your Device:</strong> All biometric verification is
            executed exclusively by the hardware-level Secure Enclave / Trusted Execution Environment
            (TEE) of your physical mobile device using native OS APIs (Android BiometricPrompt and iOS
            LocalAuthentication).
          </li>
          <li>
            <strong>Zero Server Biometric Storage:</strong> REVELA servers, municipal databases, and
            cloud backends have no access to, do not process, and never store your biometric signatures,
            fingerprint templates, or facial scans.
          </li>
        </ul>

        <h2>5. How to Control, Inspect, or Clear Your Storage</h2>
        <p>
          You have full control over your client-side storage at all times through your browser
          settings:
        </p>
        <ul>
          <li>
            <strong>Inspecting Local Storage in Chrome / Edge / Brave:</strong> Open Developer Tools
            (press <code>F12</code> or <code>Ctrl+Shift+I</code>), select the <strong>Application</strong>{" "}
            tab, expand <strong>Local Storage</strong> in the left pane, and select your REVELA domain.
          </li>
          <li>
            <strong>Clearing Local Storage &amp; Cookies:</strong> You can clear storage for the REVELA
            site at any time via your browser's Privacy &amp; Security settings, or by clicking "Clear
            Browsing Data".
          </li>
          <li>
            <strong>Operational Effect of Clearing Storage:</strong> Clearing your storage will
            immediately log you out (by removing <code>revela_token</code>) and reset your interface
            theme back to system default. No municipal records or submitted inspection reports on the
            server will be lost or affected.
          </li>
        </ul>

        <h2>6. Legal Compliance &amp; Regulatory Alignment</h2>
        <p>
          This policy and our data handling practices are designed to comply with:
        </p>
        <ul>
          <li>
            <strong>Republic Act No. 10173:</strong> The Data Privacy Act of 2012 (DPA) of the
            Philippines and its Implementing Rules and Regulations (IRR).
          </li>
          <li>
            <strong>Republic Act No. 10175:</strong> The Cybercrime Prevention Act of 2012.
          </li>
          <li>
            <strong>National Privacy Commission (NPC) Advisory Opinions:</strong> Aligning with NPC
            guidance on transparency, automated data processing, and user consent for public sector
            systems.
          </li>
        </ul>

        <h2>7. Policy Amendments &amp; Inquiries</h2>
        <p>
          The Municipality of Mataasnakahoy reserves the right to update this policy when new
          features, APIs, or statutory mandates are introduced. Revisions will be reflected with an
          updated "Last Updated" date at the top of this document.
        </p>
        <p>
          For questions, technical clarifications, or Data Privacy inquiries regarding this policy,
          please contact:
        </p>
        <ul>
          <li>
            <strong>Office:</strong> Business Permits and Licensing Office (BPLO)
          </li>
          <li>
            <strong>Address:</strong> Municipal Hall, Poblacion, Mataasnakahoy, Batangas, Philippines
          </li>
          <li>
            <strong>Email:</strong>{" "}
            <a href="mailto:mkahoy.bplo@gmail.com" className="legal-link">
              mkahoy.bplo@gmail.com
            </a>
          </li>
        </ul>

        <div className="legal-page-restricted">
          RESTRICTED ACCESS: Authorized BPLO personnel only. Violators will be prosecuted under RA 10175.
        </div>

        <div className="legal-page-footer">
          Powered by <strong>REVELA</strong>
          <br />
          &copy; 2026 Municipality of Mataasnakahoy &mdash; Business Permits and Licensing Office (BPLO).
          All rights reserved.
        </div>
      </div>
    </div>
  );
}
