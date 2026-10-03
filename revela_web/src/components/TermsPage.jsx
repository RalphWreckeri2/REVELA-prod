import LegalDocNav from "./LegalDocNav";
import "../styles/global.css";

/**
 * Terms and Conditions for the REVELA platform.
 * Supports standalone route rendering (/terms) and in-modal rendering.
 */
export default function TermsPage({ onSwitchDoc, isModal = false }) {
  return (
    <div className={`legal-page-container ${isModal ? "legal-page-container--modal" : ""}`}>
      <div className="legal-page-content">
        <LegalDocNav activeDoc="terms" onSwitchDoc={onSwitchDoc} isModal={isModal} />

        <span className="legal-page-eyebrow">Mataasnakahoy BPLO &bull; Official Terms of Service</span>
        <h1>Terms and Conditions for REVELA</h1>
        <div className="legal-page-divider" />
        <p className="legal-page-subtitle">
          Last Updated: October 2026 &bull; Official Governance &amp; User Agreement
        </p>

        <p>
          Welcome to REVELA ("the Service"), the municipal geospatial intelligence and field
          inspection platform operated by the Municipality of Mataasnakahoy through its Business
          Permits and Licensing Office (BPLO). These Terms and Conditions ("Terms") govern your
          access to and use of the REVELA administrative web dashboard ("Web Portal") and the
          inspector field mobile application ("Mobile App"). Please read these Terms thoroughly
          before accessing the Service.
        </p>
        <p>
          By accessing, logging in, or otherwise utilizing the Service, you signify your unreserved
          agreement to be legally bound by these Terms, our Privacy Policy, and our Cookie &amp; Web
          Storage Policy.
        </p>

        <div className="legal-page-notice">
          <p>
            RESTRICTED GOVERNMENT SERVICE NOTICE: Access to REVELA is strictly limited to authorized
            officials and personnel of the Municipality of Mataasnakahoy. Any unauthorized access,
            attempted breach, or unauthorized disclosure of municipal data is punishable under
            Republic Act No. 10175 (Cybercrime Prevention Act of 2012) and applicable penal laws.
          </p>
        </div>

        <h2>1. Acceptance of Terms &amp; Legal Capacity</h2>
        <p>
          By creating an account, authenticating credentials, or performing any action within the
          REVELA platform, you acknowledge that you are an authorized agent or employee of the
          Municipality of Mataasnakahoy and that you have read, understood, and agreed to adhere to
          these Terms. If you do not agree to these Terms, you must immediately cease use of the
          platform and notify the system administrator.
        </p>

        <h2>2. Description of the REVELA Dual-Platform Service</h2>
        <p>
          REVELA is an integrated dual-platform regulatory enforcement system engineered for
          municipal administration:
        </p>
        <ul>
          <li>
            <strong>Administrative Web Portal:</strong> A desktop web dashboard restricted to
            municipal administrators ("Administrators", "SUPER_ADMIN", "System Administrator") to
            manage the municipal business registry, review geospatial GIS layers, trigger automated
            detection of unregistered businesses, dispatch field inspection tasks, inspect evidence,
            and generate official compliance analytics.
          </li>
          <li>
            <strong>Mobile Field Inspection App:</strong> A specialized mobile application restricted
            to authorized field inspection personnel ("Inspectors") to receive inspection assignments,
            navigate to establishment locations, capture photographic evidence, record geospatial
            coordinates, and submit verified inspection findings.
          </li>
        </ul>

        <h2>3. Authorized Personnel, Eligibility &amp; Role-Based Access</h2>
        <p>
          <strong>Eligibility:</strong> Access is granted solely at the discretion of the BPLO and
          Municipal Government of Mataasnakahoy. Accounts are non-transferable and tied to specific
          public service appointments.
        </p>
        <p>
          <strong>Role-Based Separation of Duties:</strong>
        </p>
        <ul>
          <li>The Web Portal is strictly restricted to accounts with administrative roles.</li>
          <li>The Mobile App is strictly restricted to accounts with inspector roles.</li>
          <li>
            Any attempt to bypass role boundaries or exploit system privileges constitutes a severe
            breach of security and grounds for immediate account termination and administrative
            investigation.
          </li>
        </ul>

        <h2>4. Account Security, Credentials &amp; Authentication</h2>
        <p>
          <strong>Credential Safeguarding:</strong> You are strictly responsible for maintaining the
          confidentiality of your login credentials, including passwords and Two-Factor Authentication
          (2FA) TOTP secret codes. You must never share, write down in public view, or delegate your
          account to another individual.
        </p>
        <p>
          <strong>Re-Authentication &amp; Timeouts:</strong> To safeguard municipal records, the Service
          enforces session timeout policies and may require fresh authentication upon launching the
          Mobile App or accessing sensitive administrative settings.
        </p>
        <p>
          <strong>Mandatory Incident Reporting:</strong> You must immediately inform the BPLO System
          Administrator at <code>mkahoy.bplo@gmail.com</code> if you suspect your account has been
          compromised, if an authorized device is lost or stolen, or if any unauthorized activity is
          detected.
        </p>

        <h2>5. Authorized Official Use &amp; User Conduct Guidelines</h2>
        <p>
          You agree to utilize REVELA exclusively for the execution of your lawful municipal duties.
          You shall <strong>NOT</strong>:
        </p>
        <ul>
          <li>Falsify, manipulate, or misrepresent inspection findings, notes, or business compliance statuses.</li>
          <li>Attempt to spoof, alter, or spoof GPS coordinates or tamper with geotagged inspection evidence.</li>
          <li>Download, export, or disseminate municipal business registry data for personal, commercial, or non-official purposes.</li>
          <li>Introduce malware, viruses, malicious scripts, or reverse-engineer the Service's application code or API endpoints.</li>
          <li>Use automated bots, scrapers, or unauthorized third-party scripts to access the system.</li>
          <li>Interfere with the network connectivity, database integrity, or server infrastructure of REVELA.</li>
        </ul>

        <h2>6. Field Data, Inspection Evidence &amp; Chain of Custody</h2>
        <p>
          <strong>Official Records:</strong> All reports, remarks, photographs, GPS coordinates, and
          compliance tags submitted by Inspectors through the Mobile App constitute official public
          records under the legal custody and ownership of the Municipality of Mataasnakahoy.
        </p>
        <p>
          <strong>Evidentiary Integrity:</strong> Inspectors must ensure that photographs submitted
          accurately reflect the current facade, signage, and physical location of inspected establishments.
          Tampering with, fabricating, or submitting misleading evidence constitutes official misconduct
          subject to disciplinary and penal sanctions.
        </p>
        <p>
          <strong>License Grant:</strong> By submitting data through the Service, you grant the
          Municipality an unconditional, perpetual, irrevocable, worldwide license to utilize, store,
          modify, and present such data for municipal regulation, taxation, and legal proceedings.
        </p>

        <h2>7. Mobile Device Security, Offline Queuing &amp; Biometrics</h2>
        <p>
          <strong>Offline Queue Responsibility:</strong> The Mobile App incorporates offline queue
          capabilities. Inspectors operating in low-signal areas are responsible for reconnecting to a
          secure network to ensure cached inspection reports successfully synchronize with the central
          server.
        </p>
        <p>
          <strong>Device Biometrics:</strong> Biometric unlock on supported devices operates exclusively
          through the device's local hardware enclave. No biometric data is ever stored on or transmitted
          to REVELA infrastructure. Inspectors remain responsible for securing their physical device with
          a strong PIN/passcode.
        </p>

        <h2>8. Business Registry Data &amp; Administrative Responsibilities</h2>
        <p>
          Administrators uploading business registry data (via CSV or database synchronization) must
          ensure that source files are accurate, legitimate, and authorized. The Municipality retains the
          authority to cross-verify all registry entries against national agencies (e.g., DTI, SEC, BIR).
        </p>

        <h2>9. Third-Party Geospatial &amp; Mapping Services</h2>
        <p>
          The platform integrates the Google Maps Platform API for satellite visualization, cartography,
          and geocoding. While the platform strives for high precision, cartographic layers, satellite
          imagery age, and address estimations provided by third parties are informational aids. In the
          event of real property or boundary disputes, official municipal cadastral records and
          geodetic surveys shall prevail.
        </p>

        <h2>10. Intellectual Property Rights &amp; Software Ownership</h2>
        <p>
          All intellectual property rights in and to the REVELA platform—including its source code,
          geospatial clustering algorithms, visual user interface, designs, system workflows, and
          documentation—are the exclusive property of the Municipality of Mataasnakahoy and its
          designated project developers. Nothing in these Terms grants users any right, title, or interest
          in the software beyond the limited, revocable license to use it in the course of official duties.
        </p>

        <h2>11. Data Confidentiality &amp; Privacy Compliance</h2>
        <p>
          All users must strictly observe the confidentiality of commercial information, business
          financial declarations, and personal taxpayer data accessed through the platform in compliance
          with Republic Act No. 10173 (Data Privacy Act of 2012). Unauthorized disclosure of confidential
          records is subject to statutory penalties under national law.
        </p>

        <h2>12. Disclaimers and Warranties</h2>
        <p>
          THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS FOR MUNICIPAL ADMINISTRATIVE
          USE. TO THE MAXIMUM EXTENT PERMITTED UNDER APPLICABLE LAW, THE SERVICE DISCLAIMS ALL WARRANTIES,
          EXPRESS OR IMPLIED, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE,
          AND NON-INFRINGEMENT. WE DO NOT WARRANT THAT SYSTEM OPERATION WILL BE ENTIRELY UNINTERRUPTED,
          DEFECT-FREE, OR IMMUNE TO NETWORK DISRUPTIONS.
        </p>

        <h2>13. Limitation of Liability</h2>
        <p>
          TO THE EXTENT PERMITTED BY PHILIPPINE LAW, IN NO EVENT SHALL THE MUNICIPALITY OF MATAASNAKAHOY,
          ITS OFFICERS, SYSTEM DEVELOPERS, OR AFFILIATES BE LIABLE FOR ANY INDIRECT, INCIDENTAL,
          CONSEQUENTIAL, OR SPECIAL DAMAGES ARISING OUT OF THE USE OR INABILITY TO USE THE SERVICE, EVEN
          IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
        </p>

        <h2>14. Account Suspension, Revocation &amp; Penal Sanctions</h2>
        <p>
          <strong>Administrative Sanctions:</strong> The Municipality reserves the right to immediately
          suspend or terminate user accounts that violate these Terms, exhibit anomalous security behavior,
          or upon cessation of an employee's official duties with the BPLO.
        </p>
        <p>
          <strong>Statutory Prosecution:</strong> Any unauthorized intrusion, alteration of records,
          denial-of-service attack, or theft of data will be referred to law enforcement authorities for
          prosecution under:
        </p>
        <ul>
          <li><strong>Republic Act No. 10175:</strong> The Cybercrime Prevention Act of 2012.</li>
          <li><strong>Republic Act No. 6713:</strong> Code of Conduct and Ethical Standards for Public Officials and Employees.</li>
          <li><strong>Republic Act No. 3019:</strong> Anti-Graft and Corrupt Practices Act.</li>
        </ul>

        <h2>15. Amendments to Terms</h2>
        <p>
          The Municipality of Mataasnakahoy reserves the right to revise or update these Terms to reflect
          new legislative requirements, municipal tax ordinances, or platform technological updates.
          Notice of material changes will be published on the platform with the updated effective date.
        </p>

        <h2>16. Governing Law, Jurisdiction &amp; Inquiries</h2>
        <p>
          These Terms shall be governed by and construed in accordance with the laws of the Republic of
          the Philippines. Any legal action or dispute arising out of these Terms shall be instituted
          exclusively in the competent courts of the Province of Batangas, Philippines.
        </p>
        <p>
          For questions regarding these Terms, contact:
        </p>
        <ul>
          <li>
            <strong>Office:</strong> Business Permits and Licensing Office (BPLO)
          </li>
          <li>
            <strong>Municipality:</strong> Local Government Unit of Mataasnakahoy, Batangas, Philippines
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