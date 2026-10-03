import LegalDocNav from "./LegalDocNav";
import "../styles/global.css";

/**
 * Privacy Policy for the REVELA platform.
 * Supports standalone route rendering (/privacy) and in-modal rendering.
 */
export default function PrivacyPage({ onSwitchDoc, isModal = false }) {
  return (
    <div className={`legal-page-container ${isModal ? "legal-page-container--modal" : ""}`}>
      <div className="legal-page-content">
        <LegalDocNav activeDoc="privacy" onSwitchDoc={onSwitchDoc} isModal={isModal} />

        <span className="legal-page-eyebrow">Mataasnakahoy BPLO &bull; Data Privacy Compliance</span>
        <h1>Privacy Policy for REVELA</h1>
        <div className="legal-page-divider" />
        <p className="legal-page-subtitle">
          Last Updated: October 2026 &bull; In Full Compliance with RA 10173 (Data Privacy Act of 2012)
        </p>

        <p>
          This Privacy Policy sets forth how the Municipality of Mataasnakahoy ("we," "us," or "our"),
          through the Business Permits and Licensing Office (BPLO), collects, processes, protects,
          and manages personal and regulatory information in connection with your use of the REVELA
          geospatial intelligence and field inspection platform, encompassing both the administrative
          web dashboard ("Web Portal") and the inspector field application ("Mobile App").
        </p>

        <div className="legal-page-notice">
          <p>
            Official Personnel Notice: Access to REVELA is strictly restricted to authorized municipal
            personnel and designated public officers. This system is not accessible to the general
            public. All data processing is executed pursuant to official municipal mandates under
            Philippine law.
          </p>
        </div>

        <h2>1. Statutory Mandate &amp; Lawful Basis for Processing</h2>
        <p>
          The Municipality processes personal data and business establishment records pursuant to its
          statutory powers, duties, and public authority under:
        </p>
        <ul>
          <li>
            <strong>Republic Act No. 7160 (Local Government Code of 1991):</strong> Mandating local
            government units to enact tax ordinances, regulate commercial enterprises, issue business
            permits and licenses, and safeguard local public revenue and consumer welfare.
          </li>
          <li>
            <strong>Republic Act No. 10173 (Data Privacy Act of 2012):</strong> In accordance with
            Section 12 (Criteria for Lawful Processing of Personal Information) and Section 13
            (Processing of Sensitive Personal Information), specifically for the fulfillment of
            official mandates, regulatory enforcement, and public authority vested in the LGU.
          </li>
          <li>
            <strong>Mataasnakahoy Municipal Revenue Code &amp; Executive Orders:</strong> Governing
            local business registration, inspection protocols, and regulatory compliance.
          </li>
        </ul>

        <h2>2. Information We Collect</h2>
        <p>
          We collect and process the following categories of information strictly to operate,
          audit, and maintain the REVELA platform:
        </p>

        <ul>
          <li>
            <strong>Personal Account Information (Personnel &amp; Officials):</strong> When an authorized
            account is provisioned, we record your full name, official government/municipal email address,
            assigned role (e.g., "System Administrator," "Admin," "SUPER_ADMIN," "Inspector"), and contact
            number. Passwords are cryptographically salted and hashed using modern one-way hash functions.
            When Two-Factor Authentication (2FA) is activated, we store a cryptographically generated TOTP
            secret key to verify identity.
          </li>
          <li>
            <strong>Field Inspection &amp; Geospatial Data (from Mobile App):</strong> When Inspectors
            carry out field operations, the Mobile App collects and submits:
            <ul>
              <li>Photographic evidence of commercial facades, signage, and inspection premises.</li>
              <li>Official inspection findings, compliance checklists, notes, and remarks.</li>
              <li>
                High-accuracy GPS coordinates (latitude, longitude, altitude, and timestamp) captured at
                the exact point of report submission to verify spatial integrity.
              </li>
            </ul>
          </li>
          <li>
            <strong>Biometric Integrity Guarantee (Mobile App):</strong> For devices supporting
            biometric authentication (fingerprint scan, Face ID/facial unlock):
            <ul>
              <li>
                <strong>Biometric data remains strictly on your personal device.</strong> Authentication
                is executed entirely within your device's hardware Secure Enclave / Trusted Execution
                Environment via native OS frameworks (Android BiometricPrompt / iOS LocalAuthentication).
              </li>
              <li>
                REVELA never transmits, receives, processes, or stores your biometric templates on any
                server or database.
              </li>
            </ul>
          </li>
          <li>
            <strong>Business Registry &amp; Taxpayer Data (Web Portal):</strong> When Administrators
            upload registry spreadsheets (e.g., CSV, Excel) or synchronize municipal database records:
            <ul>
              <li>Business registered name, trade name/DBA, and registration serial numbers.</li>
              <li>Owner/taxpayer names, contact details, and registered address.</li>
              <li>Business classification, line of business, permit status, and tax assessment data.</li>
            </ul>
          </li>
          <li>
            <strong>Geospatial &amp; Technical Usage Data:</strong> Automatically collected telemetry
            including:
            <ul>
              <li>Geocoded addresses derived from the Google Maps Platform API.</li>
              <li>Algorithmically detected unregistered businesses and spatial anomaly flags.</li>
              <li>
                System audit logs, IP addresses, browser user agents, timestamps, and operator actions
                recorded for security compliance and fraud prevention.
              </li>
            </ul>
          </li>
        </ul>

        <h2>3. How We Use Collected Information</h2>
        <p>
          Information collected within the platform is utilized exclusively for official municipal
          purposes:
        </p>
        <ul>
          <li>
            <strong>Platform Operation &amp; Role-Based Security:</strong> To verify user identities,
            enforce strict role separation, prevent unauthorized administrative access, and audit platform
            activity.
          </li>
          <li>
            <strong>Regulatory Enforcement &amp; Permitting:</strong> To maintain the municipal business
            registry, schedule and dispatch field inspections, cross-reference operating businesses
            against active permits, and verify tax compliance.
          </li>
          <li>
            <strong>Geospatial Analytics &amp; Hotspot Mapping:</strong> To generate visual compliance
            maps, identify zones of unregistered economic activity, and optimize municipal inspector
            dispatch routes.
          </li>
          <li>
            <strong>Official Municipal Reporting:</strong> To generate executive reports, compliance
            summaries, and evidence packages for official local government hearings and tax assessments.
          </li>
          <li>
            <strong>System Communications &amp; Alerts:</strong> To transmit task assignments,
            two-factor verification prompts, password recovery emails, and urgent municipal system
            bulletins.
          </li>
        </ul>

        <h2>4. Data Sharing, Disclosure &amp; Third Parties</h2>
        <p>
          All collected data is treated as confidential government records. <strong>We do not sell,
          monetize, lease, or commercially distribute your personal information or municipal data under
          any circumstances.</strong>
        </p>
        <p>
          Information may be disclosed only under the following strictly defined conditions:
        </p>
        <ul>
          <li>
            <strong>Third-Party Mapping Provider (Google Maps Platform):</strong> We utilize the Google
            Maps Platform API to deliver satellite imagery, map rendering, and geocoding. Establishing
            coordinates and addresses may be processed by Google in accordance with the{" "}
            <a
              href="https://policies.google.com/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="legal-link"
            >
              Google Privacy Policy
            </a>.
          </li>
          <li>
            <strong>Inter-Agency Coordination:</strong> In accordance with statutory protocols, data
            may be shared with authorized oversight entities including the Commission on Audit (COA),
            Bureau of Internal Revenue (BIR), Department of the Interior and Local Government (DILG),
            or law enforcement authorities pursuant to valid legal process.
          </li>
          <li>
            <strong>Legal &amp; Judicial Requirements:</strong> We will disclose information if required
            by law, court order, search warrant, subpoena, or lawful directive from the National Privacy
            Commission (NPC).
          </li>
        </ul>

        <h2>5. Information Security &amp; Technical Safeguards</h2>
        <p>
          We implement institutional, physical, and technical safeguards to ensure the confidentiality,
          integrity, and availability of personal and municipal data:
        </p>
        <ul>
          <li>
            <strong>Data in Transit:</strong> All communications between client devices and REVELA
            servers are encrypted using Transport Layer Security (TLS 1.3 / HTTPS).
          </li>
          <li>
            <strong>Authentication Controls:</strong> Strong password hashing algorithms (bcrypt/argon2),
            time-based one-time password (TOTP) two-factor authentication, and automated session timeouts.
          </li>
          <li>
            <strong>Role-Based Access Control (RBAC):</strong> Granular permissions ensuring Inspectors
            only access their designated tasks, while Administrative features remain locked to verified
            BPLO Administrators.
          </li>
          <li>
            <strong>Evidence Storage Hygiene:</strong> Automated storage retention monitoring and secure
            ZIP archival tools allowing administrators to download verifiable local archives before purging
            aged server evidence files.
          </li>
        </ul>

        <h2>6. Data Retention &amp; Disposal</h2>
        <p>
          Municipal regulatory records, taxpayer profiles, and inspection reports are retained in
          accordance with the National Archives of the Philippines (NAP) Act of 2007 (RA 9470),
          accounting regulations of the Commission on Audit (COA), and municipal retention schedules.
        </p>
        <p>
          Aged photographic evidence may be archived to encrypted offline storage according to
          established BPLO cutoff cycles (30, 90, 180, or 365 days) to ensure server storage integrity
          while maintaining complete non-repudiable audit logs.
        </p>

        <h2>7. Rights of Data Subjects under RA 10173</h2>
        <p>
          Under the Philippine Data Privacy Act of 2012, individuals whose personal data is processed
          hold the following statutory rights:
        </p>
        <ul>
          <li>
            <strong>Right to Be Informed:</strong> To know whether personal data pertaining to you is
            being processed, including the purpose and categories of data involved.
          </li>
          <li>
            <strong>Right to Access:</strong> To obtain reasonable access to your personal data held by
            the Municipality upon written verification of identity.
          </li>
          <li>
            <strong>Right to Rectification:</strong> To dispute inaccuracies in your personal data and
            request timely correction or updating.
          </li>
          <li>
            <strong>Right to Erasure or Blocking:</strong> To request suspension, withdrawal, or
            blocking of personal data that is incomplete, outdated, false, or unlawfully processed,
            subject to official government record retention statutes.
          </li>
          <li>
            <strong>Right to Damages:</strong> To be indemnified for substantiated damages incurred due
            to inaccurate, incomplete, or unlawful processing of personal data.
          </li>
          <li>
            <strong>Right to File a Complaint:</strong> To lodge a formal complaint with the National
            Privacy Commission (NPC) at{" "}
            <a
              href="https://www.privacy.gov.ph"
              target="_blank"
              rel="noopener noreferrer"
              className="legal-link"
            >
              privacy.gov.ph
            </a>.
          </li>
        </ul>

        <h2>8. Cookie &amp; Web Storage Reference</h2>
        <p>
          The REVELA Web Portal uses essential client-side HTML5 Web Storage (<code>localStorage</code>)
          to secure active user sessions and store visual theme preferences. For full details on our
          storage mechanisms and your controls, please review our comprehensive{" "}
          <button
            type="button"
            className="legal-inline-btn"
            onClick={() => (onSwitchDoc ? onSwitchDoc("cookies") : (window.location.href = "/cookies"))}
          >
            Cookie &amp; Web Storage Policy
          </button>.
        </p>

        <h2>9. Contact Information &amp; Data Protection Officer</h2>
        <p>
          For questions, clarifications, or to exercise your rights under the Data Privacy Act of 2012,
          please contact:
        </p>
        <ul>
          <li>
            <strong>Office:</strong> Business Permits and Licensing Office (BPLO)
          </li>
          <li>
            <strong>Agency:</strong> Local Government Unit of Mataasnakahoy
          </li>
          <li>
            <strong>Postal Address:</strong> Municipal Hall, Poblacion, Mataasnakahoy, Batangas 4223,
            Philippines
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