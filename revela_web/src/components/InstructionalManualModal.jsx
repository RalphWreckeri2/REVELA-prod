import React, { useState, useMemo } from "react";
import { createPortal } from "react-dom";
import municipalSeal from "../assets/seal.png";

const docStyles = {
  subheading: {
    fontSize: "16px",
    fontWeight: 700,
    color: "var(--color-ink)",
    margin: "24px 0 10px 0",
    paddingBottom: "6px",
    borderBottom: "1px solid var(--color-border-soft)",
  },
  list: {
    margin: "8px 0 16px 20px",
    padding: 0,
    fontSize: "13.5px",
    lineHeight: "1.65",
  },
  code: {
    background: "var(--color-hover)",
    padding: "2px 6px",
    borderRadius: "4px",
    fontFamily: "monospace",
    fontSize: "12px",
    color: "var(--color-primary-dark)",
  },
  calloutInfo: {
    background: "rgba(16, 185, 129, 0.08)",
    borderLeft: "4px solid var(--color-primary, #10b981)",
    padding: "12px 16px",
    borderRadius: "0 8px 8px 0",
    margin: "16px 0",
    fontSize: "13px",
    lineHeight: "1.55",
  },
  calloutWarning: {
    background: "rgba(245, 158, 11, 0.1)",
    borderLeft: "4px solid #f59e0b",
    padding: "12px 16px",
    borderRadius: "0 8px 8px 0",
    margin: "16px 0",
    fontSize: "13px",
    lineHeight: "1.55",
  },
  workflowBox: {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    padding: "10px 14px",
    borderRadius: "8px",
    fontSize: "12.5px",
    fontWeight: 600,
    color: "var(--color-ink)",
    margin: "10px 0",
    overflowX: "auto",
  },
  formulaBox: {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    padding: "14px 18px",
    borderRadius: "10px",
    fontSize: "15px",
    color: "var(--color-primary-dark)",
    margin: "14px 0",
    textAlign: "center",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: "12.5px",
  },
  th: {
    textAlign: "left",
    padding: "8px 12px",
    borderBottom: "2px solid var(--color-border)",
    color: "var(--color-muted)",
    fontWeight: 700,
    textTransform: "uppercase",
    fontSize: "11px",
  },
  td: {
    padding: "10px 12px",
    borderBottom: "1px solid var(--color-border-soft)",
    verticalAlign: "top",
    lineHeight: "1.45",
  },
  faqItem: {
    marginBottom: "14px",
    padding: "12px 16px",
    borderRadius: "10px",
    background: "var(--color-surface)",
    border: "1px solid var(--color-border-soft)",
  },
  faqQ: {
    fontWeight: 700,
    fontSize: "13.5px",
    color: "var(--color-ink)",
    marginBottom: "6px",
  },
  faqA: {
    fontSize: "13px",
    color: "var(--color-muted)",
    lineHeight: "1.5",
  },
};

const getManualSections = () => [
  {
    id: "overview",
    number: "1.0",
    title: "System Overview & Architecture",
    badge: "Architecture",
    content: (
      <div>
        <p>
          <strong>REVELA</strong> is an enterprise geospatial business-intelligence and compliance monitoring platform engineered specifically for the <strong>Business Permit and Licensing Office (BPLO)</strong> of the <strong>Municipality of Mataasnakahoy, Batangas</strong>.
        </p>
        <p>
          The system reconciles real-time commercial map listings (sourced via Google Places) against the municipal registry. Potential unregistered, expired, or non-compliant establishments are automatically flagged on a high-precision geospatial canvas and queued for field verification.
        </p>

        <div style={docStyles.calloutInfo}>
          <strong>Cloud &amp; Platform Infrastructure:</strong>
          <ul style={{ margin: "6px 0 0 16px", padding: 0, fontSize: "13px" }}>
            <li><strong>Web Admin Portal (<code>revela_web</code>):</strong> Hosted on Vercel at <code>https://revelasys.site</code> for administrative management, detection scans, analytics, and dispatching.</li>
            <li><strong>Backend REST API &amp; Database (<code>revela_backend</code>):</strong> Hosted on Railway Docker + MySQL 8.x (<code>https://api.revelasys.site</code>).</li>
            <li><strong>Mobile Field App (<code>revela_mobile</code>):</strong> Flutter Android client distributed as a standalone release APK (<code>revela.apk</code>) hosted on the web portal.</li>
          </ul>
        </div>
      </div>
    ),
  },
  {
    id: "roles",
    number: "2.0",
    title: "User Roles & Access Control Matrix",
    badge: "R.A. 10175",
    content: (
      <div>
        <p>Access to REVELA is strictly role-governed across three distinct administrative tiers:</p>
        <div style={{ overflowX: "auto", margin: "14px 0" }}>
          <table style={docStyles.table}>
            <thead>
              <tr>
                <th style={docStyles.th}>Role</th>
                <th style={docStyles.th}>Platform</th>
                <th style={docStyles.th}>Operational Responsibilities &amp; Privileges</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={docStyles.td}><strong>Super Administrator</strong><br /><code style={docStyles.code}>SUPER_ADMIN</code></td>
                <td style={docStyles.td}>Web Portal</td>
                <td style={docStyles.td}>Full system administration; provisioning Admin and Inspector user accounts; setting WLC weights and BPLO Base Station coordinates; purging server evidence photos; auditing system diagnostics.</td>
              </tr>
              <tr>
                <td style={docStyles.td}><strong>Administrator</strong><br /><code style={docStyles.code}>Admin</code></td>
                <td style={docStyles.td}>Web Portal</td>
                <td style={docStyles.td}>Day-to-day operations; importing and synchronizing official registry CSV/Excel records; initiating automated detection scans; assigning inspection dispatches; verifying submitted field evidence; exporting reports.</td>
              </tr>
              <tr>
                <td style={docStyles.td}><strong>Field Inspector</strong><br /><code style={docStyles.code}>Inspector</code></td>
                <td style={docStyles.td}>Mobile App (Android)</td>
                <td style={docStyles.td}>On-site inspection of assigned flagged businesses; field discovery of unrecorded commercial entities (Yellow Flags); capturing evidence photos; drafting on-site compliance notices; operating in offline SQLite mode.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div style={docStyles.calloutWarning}>
          <strong>Legal Warning (R.A. 10175 — Cybercrime Prevention Act of 2012):</strong>
          <br />
          All actions, coordinate modifications, and inspection approvals are permanently logged with timestamps and user identifiers. Unauthorized access, account tampering, or credential sharing is strictly punishable under Philippine law.
        </div>
      </div>
    ),
  },
  {
    id: "web-portal",
    number: "3.0",
    title: "Web Admin Portal Operating Procedures",
    badge: "Web Admin",
    content: (
      <div>
        <h4 style={docStyles.subheading}>3.1 Authentication &amp; Security Controls</h4>
        <ul style={docStyles.list}>
          <li><strong>Direct Sign-in:</strong> Enter authorized municipal email or username and password, then click <em>Sign in to Dashboard</em>. Standard login does <strong>not</strong> send an SMS/Email OTP.</li>
          <li><strong>Forced Temporary Password Change:</strong> If an account is flagged with temporary credentials (<code style={docStyles.code}>mustChangePassword: true</code>), the user is prompted to set a new password (min. 8 characters) before dashboard access is permitted.</li>
          <li><strong>Two-Factor Authentication (2FA):</strong> Optional security layer enabled in Settings. When active, it requires a <strong>6-digit TOTP code</strong> from an Authenticator app (e.g. Google Authenticator), not SMS.</li>
          <li><strong>Password Recovery (PhilSMS &amp; Resend):</strong> Clicking <em>Forgot password?</em> triggers a 3-step reset wizard via a <strong>5-digit OTP</strong>. The system enforces a strict limit of <strong>two (2) OTP requests per calendar day</strong>.</li>
        </ul>

        <h4 style={docStyles.subheading}>3.2 Overview Dashboard &amp; New Year Rollover</h4>
        <ul style={docStyles.list}>
          <li><strong>Hero Status Banner:</strong> Displays municipal time locked to Philippine Standard Time (PST, UTC+8) and real-time field weather for Mataasnakahoy via live Open-Meteo feed.</li>
          <li><strong>5 Core KPI Cards:</strong> Tracks (1) Registered Current Year (2026), (2) Scheduled Renewal (2027), (3) Total Registered Entities, (4) Unregistered Flags Detected, and (5) Overall Compliance Rate (%).</li>
          <li><strong>Automated January 1 Rollover:</strong> On New Year's Day, REVELA automatically marks previous-year active permits as <em>Expired</em> and shifts their map pins to <em>Red</em>, prompting the BPLO to upload the new fiscal registry.</li>
          <li><strong>Visual Calendar Widget:</strong> Displays inspection task deadlines; overdue items are highlighted in red.</li>
        </ul>

        <h4 style={docStyles.subheading}>3.3 Map &amp; Color Flags Reference</h4>
        <div style={{ overflowX: "auto", margin: "10px 0" }}>
          <table style={docStyles.table}>
            <thead>
              <tr>
                <th style={docStyles.th}>Flag</th>
                <th style={docStyles.th}>Status</th>
                <th style={docStyles.th}>Meaning &amp; SOP Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={docStyles.td}>🟢 <strong>Green</strong></td>
                <td style={docStyles.td}>Active Business</td>
                <td style={docStyles.td}>Matches active Mayor's Permit in the registry. Baseline reference.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>🟡 <strong>Yellow</strong></td>
                <td style={docStyles.td}>Suspected Unregistered</td>
                <td style={docStyles.td}>Pinned manually by admin or field inspector via ground surveillance. Priority dispatch lead.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>🔴 <strong>Red</strong></td>
                <td style={docStyles.td}>Detected Unregistered</td>
                <td style={docStyles.td}>Commercial entity detected via Google Places scan without a matching municipal permit, or expired permit rollover.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>🟠 <strong>Orange</strong></td>
                <td style={docStyles.td}>Under Monitoring / Warning</td>
                <td style={docStyles.td}>Served formal administrative notice (1st, 2nd, or 3rd Notice). Monitored for appearance at BPLO counter.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>🟣 <strong>Purple</strong></td>
                <td style={docStyles.td}>Closed / Abandoned</td>
                <td style={docStyles.td}>Structure confirmed vacant, demolished, or officially ceased operations. Archived from dispatches.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>⚫ <strong>Black</strong></td>
                <td style={docStyles.td}>Blacklisted / Non-Responsive</td>
                <td style={docStyles.td}>Hostile, uncooperative, or fraudulent commercial activity. Escalated to legal action.</td>
              </tr>
              <tr>
                <td style={docStyles.td}>🔵 <strong>Blue</strong></td>
                <td style={docStyles.td}>In Inspection (Filter)</td>
                <td style={docStyles.td}>Operational filter category (<code style={docStyles.code}>in_inspection</code>) isolating pins currently assigned or under field audit.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h4 style={docStyles.subheading}>3.4 Automated Detection Quotas &amp; Budgets</h4>
        <div style={docStyles.calloutInfo}>
          <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
            <li><strong>Monthly Detection Limit:</strong> Exactly <strong>2 scans per calendar month</strong> (resets automatically on the 1st of each month).</li>
            <li><strong>Daily Google Places API Budget:</strong> Capped at <strong>1,000 requests/day</strong> and <strong>2,000 requests/month</strong> to guarantee $0.00 bill overages.</li>
            <li><strong>Partial Scan Recovery:</strong> If the 1,000 daily request cap is reached mid-scan, progress is saved as <em>Partial</em>. The monthly quota is preserved, and scanning resumes seamlessly the next morning.</li>
          </ul>
        </div>

        <h4 style={docStyles.subheading}>3.5 Registry Upload &amp; Geocoding Caps</h4>
        <ul style={docStyles.list}>
          <li><strong>Supported File Formats:</strong> <code style={docStyles.code}>.csv</code>, <code style={docStyles.code}>.xlsx</code>, and <code style={docStyles.code}>.xls</code>.</li>
          <li><strong>Batch Size Limit:</strong> Maximum <strong>1,500 records per upload</strong> to prevent memory overload.</li>
          <li><strong>Daily Geocoding Budget:</strong> Maximum <strong>1,500 addresses geocoded per day</strong> via Google Geocoding API.</li>
          <li><strong>Pro-Tip (Quota Bypass):</strong> Pre-filling the <code style={docStyles.code}>latitude</code> and <code style={docStyles.code}>longitude</code> columns completely bypasses the Geocoding API budget, allowing immediate instant ingestion.</li>
        </ul>

        <h4 style={docStyles.subheading}>3.6 Inspection Dispatch Kanban &amp; Redo SOP</h4>
        <p>REVELA uses a strict 4-column audit lifecycle:</p>
        <div style={docStyles.workflowBox}>
          <code>[ ASSIGNED ] ──────&gt; [ REASSIGNED ] ──────&gt; [ SUBMITTED ] ──────&gt; [ VERIFIED ]</code>
        </div>
        <ul style={docStyles.list}>
          <li><strong>Assignment:</strong> Select inspector and deadline. The system strictly blocks deadlines set in the past.</li>
          <li><strong>Verification:</strong> Inspect photos, timestamps, and classifications. Click <em>Confirm &amp; Verify</em> to update the master map pin.</li>
          <li><strong>Deficiency / Redo:</strong> If evidence is blurry or improper, click <strong>Send back</strong>. The task shifts into <em>Reassigned</em> with corrective notes pushed to the inspector's device.</li>
          <li><strong>Follow-up Visits:</strong> For verified cases with active notice levels (1st/2nd/3rd notice), a <strong>Follow-up</strong> button unlocks to rapidly schedule the next compliance check.</li>
        </ul>
      </div>
    ),
  },
  {
    id: "mobile-app",
    number: "4.0",
    title: "Mobile Field App User Guide (Android)",
    badge: "Field App",
    content: (
      <div>
        <h4 style={docStyles.subheading}>4.1 Sideloading &amp; Mandatory Biometric Onboarding</h4>
        <ul style={docStyles.list}>
          <li>Download the production APK (<code style={docStyles.code}>revela.apk</code>) from <code>https://revelasys.site/revela.apk</code>.</li>
          <li>Enable <em>Install from unknown sources</em> in Android Settings.</li>
          <li><strong>Mandatory Biometrics:</strong> Upon first login and temporary password update, inspectors are automatically routed to the <strong>Mandatory Biometric Setup</strong> screen to register Fingerprint / Face ID. This encrypts credentials into the Android Keystore, allowing seamless offline access in remote barangays.</li>
        </ul>

        <h4 style={docStyles.subheading}>4.2 3-Step Inspection Wizard</h4>
        <div style={docStyles.workflowBox}>
          <code>[ Step 1: Result ] ───────&gt; [ Step 2: Photos ] ───────&gt; [ Step 3: Review ]</code>
        </div>
        <ul style={docStyles.list}>
          <li><strong>Step 1 (Result):</strong> Select physical status (<em>Registered</em>, <em>Suspected</em>, <em>Unregistered</em>, <em>Warned / Non-Compliant</em>, <em>Blacklisted</em>, or <em>Closed</em>). If warned, designate Notice Level (1st, 2nd, 3rd Notice, or Escalated).</li>
          <li><strong>Step 2 (Evidence):</strong> Capture storefront signage, operational state, and posted permits. Photos are automatically compressed on-device via <code style={docStyles.code}>flutter_image_compress</code>.</li>
          <li><strong>Step 3 (Review):</strong> GPS coordinates are pre-warmed in the background. Enter field observations and tap <em>Submit Report</em>.</li>
        </ul>

        <h4 style={docStyles.subheading}>4.3 Offline SQLite Storage &amp; Background Sync</h4>
        <p>
          In areas without 4G/5G reception, submissions are saved to the device's local SQLite database (<code style={docStyles.code}>sqflite</code> via <code style={docStyles.code}>offline_inspection_storage.dart</code>). As soon as an active internet connection is detected, the app automatically uploads queued reports in the background. A manual <strong>Sync</strong> button is also available on the Inspections screen.
        </p>

        <h4 style={docStyles.subheading}>4.4 Yellow Flag Discovery &amp; Boundary Enforcement</h4>
        <p>
          When an unrecorded business is observed, tap the floating Yellow Flag button on the Map tab. The app utilizes a spatial boundary check against the GeoJSON boundary of Mataasnakahoy:
        </p>
        <div style={docStyles.calloutWarning}>
          <strong>Spatial Boundary Lockout:</strong>
          <br />
          If your GPS coordinates fall outside municipal limits, submission is blocked with the notice:
          <em>"Location is outside the Municipality of Mataasnakahoy."</em>
          When inside municipal territory, the app automatically auto-detects and locks the corresponding barangay in the dropdown.
        </div>

        <h4 style={docStyles.subheading}>4.5 In-App Administrative Notice Generator (PDF)</h4>
        <p>
          Inspectors can draft on-site compliance letters in Filipino under <strong>Ordinansa Blg. 27-S-96</strong>. The legal compliance window dynamically adapts by notice level:
        </p>
        <ul style={docStyles.list}>
          <li><strong>First Notice (Level 1):</strong> Grants <strong>five (5) working days</strong> (<em>"sa loob ng limang (5) araw"</em>) for the proprietor to appear at the BPLO.</li>
          <li><strong>Second Notice &amp; Subsequent (Level 2+):</strong> Grants <strong>three (3) working days</strong> (<em>"sa loob ng tatlong (3) araw"</em>) before formal closure enforcement.</li>
          <li><strong>Unregistered (Level 0):</strong> Grants <strong>three (3) working days</strong> (<em>"sa loob ng tatlong (3) araw"</em>).</li>
          <li>Supports wireless Bluetooth/Wi-Fi printing or PDF export directly on-site.</li>
        </ul>
      </div>
    ),
  },
  {
    id: "wlc-policy",
    number: "5.0",
    title: "WLC Policy Modeling & Base Station Geolocation",
    badge: "Mathematical Model",
    content: (
      <div>
        <p>
          The <strong>Operational Priority Score (OPS)</strong> dictates which barangays and establishments are queued first for inspection dispatches using a Weighted Linear Combination (WLC) formula:
        </p>
        <div style={docStyles.formulaBox}>
          <strong>OPS = (w<sub>risk</sub> · R) + (w<sub>sector</sub> · S) + (w<sub>dist</sub> · D)</strong>
          <br />
          <span style={{ fontSize: "12px", color: "var(--color-muted)" }}>Subject to: w<sub>risk</sub> + w<sub>sector</sub> + w<sub>dist</sub> = 100%</span>
        </div>

        <h4 style={docStyles.subheading}>Standard Operational Presets</h4>
        <ul style={docStyles.list}>
          <li><strong>Use Default:</strong> 68% Risk Volume / 7% Sector Impact / 25% Travel Distance (standard fiscal operations).</li>
          <li><strong>Health Crisis Mode:</strong> 20% Risk Volume / 70% Sector Impact / 10% Travel Distance (prioritizes food establishments, clinics, and accommodations).</li>
          <li><strong>Business Renewal Peak:</strong> 70% Risk Volume / 20% Sector Impact / 10% Travel Distance (prioritizes expiring permits during Q1 drives).</li>
        </ul>

        <h4 style={docStyles.subheading}>Official BPLO Base Station Coordinates</h4>
        <div style={docStyles.calloutInfo}>
          <strong>Municipal Hall of Mataasnakahoy (BPLO Reference Center):</strong>
          <br />
          <code style={docStyles.code}>Latitude: 13.960413° N,  Longitude: 121.114547° E</code>
          <br />
          <span style={{ fontSize: "12px", color: "var(--color-muted)" }}>All inspector route distances and travel cost weightings (W3) are calculated relative to this reference point.</span>
        </div>

        <h4 style={docStyles.subheading}>Evidence Storage &amp; Cloud Archival</h4>
        <p>
          To maintain zero-maintenance server health on Railway, Super Administrators can select a photo cutoff (e.g. <em>Older than 6 months</em>), click <strong>Download ZIP Archive to PC</strong> (which bundles an offline HTML Dossier viewer, CSV manifest, and photos), and safely clear server disk space. Tabular audit logs and inspection notes are permanently preserved in the database.
        </p>
      </div>
    ),
  },
  {
    id: "troubleshooting",
    number: "6.0",
    title: "Troubleshooting FAQ & Emergency Contacts",
    badge: "FAQ & Support",
    content: (
      <div>
        <div style={docStyles.faqItem}>
          <div style={docStyles.faqQ}>1. Why does "Run Detection" say monthly scan limit reached?</div>
          <div style={docStyles.faqA}>The system strictly enforces 2 completed detection scans per calendar month to respect municipal API budgets. The quota resets on the 1st of each month. If a daily 1,000-request Google Places budget was hit, progress was saved as Partial and resumes tomorrow.</div>
        </div>
        <div style={docStyles.faqItem}>
          <div style={docStyles.faqQ}>2. Why are registered businesses showing as Red Flags?</div>
          <div style={docStyles.faqA}>The municipal registry in REVELA may be outdated, or the business's public Google Maps signage name differs from its legal corporate name. Ensure official trade names (DBA) are reflected in the registry.</div>
        </div>
        <div style={docStyles.faqItem}>
          <div style={docStyles.faqQ}>3. Why is the "Submit Yellow Flag" button disabled on mobile?</div>
          <div style={docStyles.faqA}>GPS coordinates have drifted outside the municipal boundary of Mataasnakahoy. Ensure high-accuracy GPS is enabled on your phone and wait for a fix inside municipal territory.</div>
        </div>
        <div style={docStyles.faqItem}>
          <div style={docStyles.faqQ}>4. How can an administrator return an erroneous field report?</div>
          <div style={docStyles.faqA}>In the Inspection Dispatch Kanban board, locate the report card in the <em>Submitted</em> column, open it, and click <strong>Send back</strong>. Enter corrective instructions; the report will return to <em>Reassigned</em> on the inspector's device.</div>
        </div>

        <div style={{ ...docStyles.calloutInfo, marginTop: "20px" }}>
          <strong>BPLO Technical Support Desk:</strong>
          <ul style={{ margin: "6px 0 0 16px", padding: 0, fontSize: "13px" }}>
            <li>Email: <a href="mailto:bplo@mataasnakahoy.gov.ph" style={{ color: "var(--color-primary)" }}>bplo@mataasnakahoy.gov.ph</a></li>
            <li>Municipal Hall Trunkline: Local 201 / 2374</li>
            <li>Jurisdiction: Business Permit and Licensing Office, Municipal Hall, Mataasnakahoy, Batangas</li>
          </ul>
        </div>
      </div>
    ),
  },
];

export default function InstructionalManualModal({ initialSectionId = "overview", onClose, isClosing }) {
  const [activeSectionId, setActiveSectionId] = useState(initialSectionId);
  const [searchQuery, setSearchQuery] = useState("");

  const sections = useMemo(() => getManualSections(), []);

  const filteredSections = useMemo(() => {
    if (!searchQuery.trim()) return sections;
    const q = searchQuery.toLowerCase();
    return sections.filter(s =>
      s.title.toLowerCase().includes(q) ||
      s.badge.toLowerCase().includes(q) ||
      s.number.includes(q)
    );
  }, [searchQuery, sections]);

  const activeSection = useMemo(() => {
    return sections.find(s => s.id === activeSectionId) || sections[0];
  }, [activeSectionId, sections]);

  const handlePrint = () => {
    window.print();
  };

  return createPortal(
    <div
      className={"modal-backdrop" + (isClosing ? " closing" : "")}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 99999,
        background: "rgba(0, 0, 0, 0.8)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "20px 16px",
      }}
      onClick={onClose}
    >
      <div
        className={"modal-panel" + (isClosing ? " closing" : "")}
        style={{
          background: "var(--color-modal-bg, #ffffff)",
          borderRadius: "20px",
          width: "min(100%, 1060px)",
          height: "min(92vh, 880px)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.35)",
          border: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 24px",
            borderBottom: "1px solid var(--color-border-soft, rgba(0,0,0,0.08))",
            background: "var(--color-surface, rgba(255, 255, 255, 0.7))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <img src={municipalSeal} alt="Mataasnakahoy Seal" style={{ width: 34, height: 34, objectFit: "contain" }} />
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--color-ink)" }}>
                  REVELA — System Instructional Manual &amp; SOP
                </h3>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    color: "var(--color-primary, #10b981)",
                    background: "var(--color-primary-light, rgba(16, 185, 129, 0.1))",
                    padding: "2px 8px",
                    borderRadius: 999,
                  }}
                >
                  Official BPLO Guide
                </span>
              </div>
              <p style={{ margin: 0, fontSize: 12, color: "var(--color-muted)" }}>
                Municipality of Mataasnakahoy, Batangas · Standard Operating Procedures
              </p>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              className="ghost-btn"
              onClick={handlePrint}
              style={{ fontSize: 12, padding: "6px 12px", display: "inline-flex", alignItems: "center", gap: 6 }}
              title="Print standard operating procedures"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 6 2 18 2 18 9" /><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><rect x="6" y="14" width="12" height="8" /></svg>
              Print SOP
            </button>
            <button
              className="modal-close-btn"
              onClick={onClose}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--color-muted, #64748b)",
                cursor: "pointer",
                padding: 6,
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          </div>
        </div>

        {/* Modal Body: Sidebar + Main Content */}
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          {/* Sidebar */}
          <div
            style={{
              width: 300,
              borderRight: "1px solid var(--color-border-soft)",
              background: "var(--color-surface)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Search Input */}
            <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--color-border-soft)" }}>
              <div style={{ position: "relative" }}>
                <svg
                  style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-muted)" }}
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <input
                  type="text"
                  placeholder="Filter chapters..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "7px 10px 7px 32px",
                    borderRadius: 8,
                    border: "1px solid var(--color-border)",
                    background: "var(--color-modal-bg)",
                    fontSize: 12.5,
                    color: "var(--color-ink)",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            </div>

            {/* Chapter List */}
            <div style={{ flex: 1, overflowY: "auto", padding: "10px 8px" }}>
              {filteredSections.map((sec) => {
                const isActive = sec.id === activeSection.id;
                return (
                  <button
                    key={sec.id}
                    type="button"
                    onClick={() => setActiveSectionId(sec.id)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "10px 12px",
                      borderRadius: 10,
                      marginBottom: 4,
                      border: "none",
                      cursor: "pointer",
                      background: isActive ? "var(--color-primary-light, rgba(16, 185, 129, 0.12))" : "transparent",
                      borderLeft: isActive ? "3px solid var(--color-primary)" : "3px solid transparent",
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: isActive ? "var(--color-primary)" : "var(--color-muted)", fontFamily: "monospace" }}>
                        CHAPTER {sec.number}
                      </span>
                      <span style={{ fontSize: 9.5, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "var(--color-hover)", color: "var(--color-muted)" }}>
                        {sec.badge}
                      </span>
                    </div>
                    <span style={{ fontSize: 13, fontWeight: isActive ? 700 : 500, color: isActive ? "var(--color-ink)" : "var(--color-muted)", lineHeight: 1.35 }}>
                      {sec.title}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Reader Canvas */}
          <div style={{ flex: 1, overflowY: "auto", padding: "30px 36px", background: "var(--color-modal-bg)" }}>
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 800,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    color: "var(--color-primary)",
                  }}
                >
                  Section {activeSection.number}
                </span>
                <span style={{ color: "var(--color-muted)" }}>•</span>
                <span style={{ fontSize: 12, color: "var(--color-muted)", fontWeight: 600 }}>
                  {activeSection.badge}
                </span>
              </div>
              <h2 style={{ fontSize: 24, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>
                {activeSection.title}
              </h2>
            </div>

            <div style={{ fontSize: 14, color: "var(--color-ink)", lineHeight: 1.65 }}>
              {activeSection.content}
            </div>
          </div>
        </div>

        {/* Modal Bottom Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "12px 24px",
            borderTop: "1px solid var(--color-border-soft)",
            background: "var(--color-surface)",
            fontSize: 12,
            color: "var(--color-muted)",
          }}
        >
          <span>REVELA Geospatial Intelligence System · BPLO Mataasnakahoy</span>
          <button
            type="button"
            className="ghost-btn"
            onClick={onClose}
            style={{ padding: "6px 14px", fontSize: 12 }}
          >
            Close Manual
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

