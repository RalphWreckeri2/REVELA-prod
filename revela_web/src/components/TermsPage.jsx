import React from "react";
import "../styles/global.css";

/**
 * A simple, unauthenticated page to display the Terms & Conditions.
 * It's styled to be clean, readable, and theme-aware.
 */
export default function TermsPage() {
  return (
    <div className="legal-page-container">
      <div className="legal-page-content">
        <span className="legal-page-eyebrow">Mataasnakahoy BPLO</span>
        <h1>Terms and Conditions for REVELA</h1>
        <div className="legal-page-divider" />
        <p className="legal-page-subtitle">Last Updated: October 26, 2023</p>

        <p>
          Welcome to REVELA ("the Service"), the geospatial intelligence and
          field inspection platform for the Municipality of Mataasnakahoy. These
          Terms and Conditions ("Terms") govern your access to and use of the
          REVELA web dashboard ("Web Portal") and the REVELA mobile application
          ("Mobile App"). Please read these Terms carefully.
        </p>
        <p>
          By accessing or using the Service, you agree to be bound by these
          Terms and our Privacy Policy.
        </p>

        <div className="legal-page-notice">
          <p>
            Notice: Access to REVELA is restricted to authorized municipal
            personnel. Unauthorized use is a violation of these Terms.
          </p>
        </div>

        <h2>1. Acceptance of Terms</h2>
        <p>
          By creating an account, logging in, or otherwise using the REVELA
          platform, you acknowledge that you have read, understood, and agree to
          be bound by these Terms. If you do not agree with these Terms, you
          must not access or use the Service.
        </p>

        <h2>2. Description of Service</h2>
        <p>
          REVELA is a dual-platform system designed for municipal business
          regulation and enforcement:
        </p>
        <ul>
          <li>
            <strong>Web Portal:</strong> An administrative dashboard for
            authorized municipal personnel ("Administrators") to manage business
            registries, visualize geospatial data, run automated detection of
            unregistered businesses, assign inspection tasks, and review field
            reports.
          </li>
          <li>
            <strong>Mobile App:</strong> A tool for authorized field personnel
            ("Inspectors") to receive inspection assignments, navigate to
            locations, and submit field reports, including notes and
            photographic evidence.
          </li>
        </ul>

        <h2>3. User Accounts and Roles</h2>
        <p>
          <strong>Eligibility:</strong> Access to the Service is restricted to
          authorized personnel of the Municipality of Mataasnakahoy.
        </p>
        <p>
          <strong>Role-Based Access:</strong>
        </p>
        <ul>
          <li>
            The Web Portal is strictly for users with "Admin," "SUPER_ADMIN," or
            "System Administrator" roles.
          </li>
          <li>
            The Mobile App is strictly for users with the "Inspector" role.
          </li>
        </ul>
        <p>
          Attempting to access a platform for which you are not authorized is a
          violation of these Terms and will result in immediate denial of
          service.
        </p>
        <p>
          <strong>Account Security:</strong> You are responsible for maintaining
          the confidentiality of your account credentials, including your
          password and any two-factor authentication (2FA) codes. You agree to
          notify the system administrator immediately of any unauthorized use of
          your account. The Service enforces re-authentication on each launch
          of the Mobile App for enhanced security.
        </p>
        <p>
          <strong>Password Changes:</strong> The system may require you to
          change a temporary or expired password before granting access. You are
          responsible for any activities that occur under your account.
        </p>

        <h2>4. Authorized Use and User Conduct</h2>
        <p>
          You agree to use the Service only for its intended official purposes.
          You shall not:
        </p>
        <ul>
          <li>Use the Service for any illegal or unauthorized purpose.</li>
          <li>
            Attempt to gain unauthorized access to other users' accounts or
            administrative functions.
          </li>
          <li>
            Upload or transmit any data that is unlawful, harmful, or infringes
            on the rights of others.
          </li>
          <li>
            Interfere with or disrupt the integrity or performance of the
            Service or the data contained therein.
          </li>
          <li>
            Use the automated detection, geocoding, or mapping features for any
            purpose other than official municipal business.
          </li>
          <li>Share your account credentials with any other person.</li>
        </ul>

        <h2>5. User-Generated Content</h2>
        <p>
          <strong>Inspector Reports:</strong> As an Inspector using the Mobile
          App, you may submit reports, notes, photographs, and location data
          ("Field Data"). By submitting Field Data, you grant the Municipality
          of Mataasnakahoy a perpetual, irrevocable, worldwide, royalty-free
          license to use, reproduce, modify, and display this data in
          connection with the operation of the Service.
        </p>
        <p>
          <strong>Administrator Content:</strong> As an Administrator, you may
          upload business registry files and manually create or modify
          geospatial flags. You are responsible for the accuracy and legality of
          any data you upload or create.
        </p>
        <p>
          <strong>Responsibility:</strong> You are solely responsible for the
          content you submit. The Service is not responsible for the accuracy or
          legality of user-generated content but reserves the right to remove
          any content that violates these Terms.
        </p>

        {/* ... other sections would continue here ... */}

        <h2>8. Disclaimers and Limitation of Liability</h2>
        <p>
          THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS,
          WITHOUT ANY WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED. WE DO
          NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, SECURE, OR
          ERROR-FREE.
        </p>
        <p>
          IN NO EVENT WILL THE SERVICE, ITS CREATORS, OR THE MUNICIPALITY OF
          MATAASNAKAHOY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL,
          CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING OUT OF OR IN CONNECTION
          WITH YOUR USE OF THE SERVICE.
        </p>

        <h2>12. Contact Us</h2>
        <p>
          If you have any questions about these Terms, please contact the system
          administrator at mkahoy.bplo@gmail.com.
        </p>

        <div className="legal-page-restricted">
          RESTRICTED ACCESS: Authorized BPLO personnel only. Violators will be
          prosecuted under RA 10175.
        </div>

        <div className="legal-page-footer">
          Powered by <strong>REVELA</strong>
          <br />
          &copy; 2026 Municipality of Mataasnakahoy — Business Permits and
          Licensing Office (BPLO). All rights reserved.
        </div>
      </div>
    </div>
  );
}