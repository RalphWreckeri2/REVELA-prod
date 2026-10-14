# Privacy Policy for REVELA

Mataasnakahoy BPLO • Data Privacy Compliance

Last Updated: October 2026 • In Full Compliance with RA 10173 (Data Privacy Act of 2012)

This Privacy Policy sets forth how the Municipality of Mataasnakahoy ("we," "us," or "our"), through the Business Permits and Licensing Office (BPLO), collects, processes, protects, and manages personal and regulatory information in connection with your use of the REVELA geospatial intelligence and field inspection platform, encompassing both the administrative web dashboard ("Web Portal") and the inspector field application ("Mobile App").

> Official Personnel Notice: Access to REVELA is strictly restricted to authorized municipal personnel and designated public officers. This system is not accessible to the general public. All data processing is executed pursuant to official municipal mandates under Philippine law.

## 1. Statutory Mandate & Lawful Basis for Processing

The Municipality processes personal data and business establishment records pursuant to its statutory powers, duties, and public authority under:

- **Republic Act No. 7160 (Local Government Code of 1991):** Mandating local government units to enact tax ordinances, regulate commercial enterprises, issue business permits and licenses, and safeguard local public revenue and consumer welfare.
- **Republic Act No. 10173 (Data Privacy Act of 2012):** In accordance with Section 12 (Criteria for Lawful Processing of Personal Information) and Section 13 (Processing of Sensitive Personal Information), specifically for the fulfillment of official mandates, regulatory enforcement, and public authority vested in the LGU.
- **Mataasnakahoy Municipal Revenue Code & Executive Orders:** Governing local business registration, inspection protocols, and regulatory compliance.

## 2. Information We Collect

We collect and process the following categories of information strictly to operate, audit, and maintain the REVELA platform:

- **Personal Account Information (Personnel & Officials):** When an authorized account is provisioned, we record your full name, official government/municipal email address, assigned role (e.g., "System Administrator," "Admin," "SUPER_ADMIN," "Inspector"), and contact number. Passwords are cryptographically salted and hashed using modern one-way hash functions. When Two-Factor Authentication (2FA) is activated, we store a cryptographically generated TOTP secret key to verify identity.
- **Field Inspection & Geospatial Data (from Mobile App):** When Inspectors carry out field operations, the Mobile App collects and submits:
  - Photographic evidence of commercial facades, signage, and inspection premises.
  - Official inspection findings, compliance checklists, notes, and remarks.
  - High-accuracy GPS coordinates (latitude, longitude, altitude, and timestamp) captured at the exact point of report submission to verify spatial integrity.
- **Biometric Integrity Guarantee (Mobile App):** For devices supporting biometric authentication (fingerprint scan, Face ID/facial unlock):
  - **Biometric data remains strictly on your personal device.** Authentication is executed entirely within your device's hardware Secure Enclave / Trusted Execution Environment via native OS frameworks (Android BiometricPrompt / iOS LocalAuthentication).
  - REVELA never transmits, receives, processes, or stores your biometric templates on any server or database.
- **Business Registry & Taxpayer Data (Web Portal):** When Administrators upload registry spreadsheets (e.g., CSV, Excel) or synchronize municipal database records:
  - Business registered name, trade name/DBA, and registration serial numbers.
  - Owner/taxpayer names, contact details, and registered address.
  - Business classification, line of business, permit status, and tax assessment data.
- **Geospatial & Technical Usage Data:** Automatically collected telemetry including:
  - Geocoded addresses derived from the Google Maps Platform API.
  - Algorithmically detected unregistered businesses and spatial anomaly flags.
  - System audit logs, IP addresses, browser user agents, timestamps, and operator actions recorded for security compliance and fraud prevention.

## 3. How We Use Collected Information

Information collected within the platform is utilized exclusively for official municipal purposes:

- **Platform Operation & Role-Based Security:** To verify user identities, enforce strict role separation, prevent unauthorized administrative access, and audit platform activity.
- **Regulatory Enforcement & Permitting:** To maintain the municipal business registry, schedule and dispatch field inspections, cross-reference operating businesses against active permits, and verify tax compliance.
- **Geospatial Analytics & Hotspot Mapping:** To generate visual compliance maps, identify zones of unregistered economic activity, and optimize municipal inspector dispatch routes.
- **Official Municipal Reporting:** To generate executive reports, compliance summaries, and evidence packages for official local government hearings and tax assessments.
- **System Communications & Alerts:** To transmit task assignments, two-factor verification prompts, password recovery emails, and urgent municipal system bulletins.

## 4. Data Sharing, Disclosure & Third Parties

All collected data is treated as confidential government records. **We do not sell, monetize, lease, or commercially distribute your personal information or municipal data under any circumstances.**

Information may be disclosed only under the following strictly defined conditions:

- **Third-Party Mapping Provider (Google Maps Platform):** We utilize the Google Maps Platform API to deliver satellite imagery, map rendering, and geocoding. Establishing coordinates and addresses may be processed by Google in accordance with the Google Privacy Policy: https://policies.google.com/privacy
- **Inter-Agency Coordination:** In accordance with statutory protocols, data may be shared with authorized oversight entities including the Commission on Audit (COA), Bureau of Internal Revenue (BIR), Department of the Interior and Local Government (DILG), or law enforcement authorities pursuant to valid legal process.
- **Legal & Judicial Requirements:** We will disclose information if required by law, court order, search warrant, subpoena, or lawful directive from the National Privacy Commission (NPC).

## 5. Information Security & Technical Safeguards

We implement institutional, physical, and technical safeguards to ensure the confidentiality, integrity, and availability of personal and municipal data:

- **Data in Transit:** All communications between client devices and REVELA servers are encrypted using Transport Layer Security (TLS 1.3 / HTTPS).
- **Authentication Controls:** Strong password hashing algorithms (bcrypt/argon2), time-based one-time password (TOTP) two-factor authentication, and automated session timeouts.
- **Role-Based Access Control (RBAC):** Granular permissions ensuring Inspectors only access their designated tasks, while Administrative features remain locked to verified BPLO Administrators.
- **Evidence Storage Hygiene:** Automated storage retention monitoring and secure ZIP archival tools allowing administrators to download verifiable local archives before purging aged server evidence files.

## 6. Data Retention & Disposal

Municipal regulatory records, taxpayer profiles, and inspection reports are retained in accordance with the National Archives of the Philippines (NAP) Act of 2007 (RA 9470), accounting regulations of the Commission on Audit (COA), and municipal retention schedules.

Aged photographic evidence may be archived to encrypted offline storage according to established BPLO cutoff cycles (30, 90, 180, or 365 days) to ensure server storage integrity while maintaining complete non-repudiable audit logs.

## 7. Rights of Data Subjects under RA 10173

Under the Philippine Data Privacy Act of 2012, individuals whose personal data is processed hold the following statutory rights:

- **Right to Be Informed:** To know whether personal data pertaining to you is being processed, including the purpose and categories of data involved.
- **Right to Access:** To obtain reasonable access to your personal data held by the Municipality upon written verification of identity.
- **Right to Rectification:** To dispute inaccuracies in your personal data and request timely correction or updating.
- **Right to Erasure or Blocking:** To request suspension, withdrawal, or blocking of personal data that is incomplete, outdated, false, or unlawfully processed, subject to official government record retention statutes.
- **Right to Damages:** To be indemnified for substantiated damages incurred due to inaccurate, incomplete, or unlawful processing of personal data.
- **Right to File a Complaint:** To lodge a formal complaint with the National Privacy Commission (NPC) at privacy.gov.ph.

## 8. Cookie & Web Storage Reference

The REVELA Web Portal uses essential client-side HTML5 Web Storage (`localStorage`) to secure active user sessions and store visual theme preferences. For full details on our storage mechanisms and your controls, please review our comprehensive Cookie & Web Storage Policy.

## 9. Contact Information & Data Protection Officer

For questions, clarifications, or to exercise your rights under the Data Privacy Act of 2012, please contact:

- **Office:** Business Permits and Licensing Office (BPLO)
- **Agency:** Local Government Unit of Mataasnakahoy
- **Postal Address:** Municipal Hall, Poblacion, Mataasnakahoy, Batangas 4223, Philippines
- **Email:** `mkahoy.bplo@gmail.com`

> RESTRICTED ACCESS: Authorized BPLO personnel only. Violators will be prosecuted under RA 10175.

Powered by **REVELA**

© 2026 Municipality of Mataasnakahoy — Business Permits and Licensing Office (BPLO). All rights reserved.
