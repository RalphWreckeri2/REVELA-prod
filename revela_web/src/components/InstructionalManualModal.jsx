import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import municipalSeal from "../assets/seal.png";

const manualSections = [
  {
    id: "overview",
    number: "1",
    title: "Getting started and navigation",
    badge: "Start here",
    content: (
      <>
        <p>
          REVELA helps the Business Permit and Licensing Office (BPLO) compare
          the business registry with map listings, review possible concerns,
          coordinate inspections, and view reports.
        </p>
        <h4>Sign in and open a page</h4>
        <ol>
          <li>Sign in with your authorized account. If prompted, complete the second verification step.</li>
          <li>Use the left navigation to open <strong>Overview</strong>, <strong>Map &amp; Flags</strong>, <strong>Registry</strong>, <strong>Analytics</strong>, <strong>Inspections</strong>, <strong>Export Reports</strong>, or <strong>Settings</strong>.</li>
          <li>Select <strong>Refresh</strong> on a page to reload its current information.</li>
          <li>Use <strong>Logout</strong> when you finish.</li>
        </ol>
        <p>
          The Overview page summarizes activity and provides shortcuts to the
          registry, map, and inspection work. The manual is available in
          <strong> Settings → Legal &amp; Support → System Instructional Manual &amp; SOP → View</strong>.
        </p>
        <div className="manual-callout manual-callout--info">
          The web portal is for Admin and Super Admin accounts. Inspectors use
          the field app for their assigned inspection work.
        </div>
      </>
    ),
  },
  {
    id: "roles",
    number: "2",
    title: "Roles and access",
    badge: "Permissions",
    content: (
      <>
        <p>Only use the actions available to your assigned role.</p>
        <div className="manual-table-wrap">
          <table>
            <thead><tr><th>Role</th><th>What the role can do</th></tr></thead>
            <tbody>
              <tr>
                <td><strong>Super Admin</strong></td>
                <td>Use the Admin web portal and manage user accounts. User Management is restricted to Super Admin.</td>
              </tr>
              <tr>
                <td><strong>Admin</strong></td>
                <td>Use day-to-day web tools: review the registry and map, run available workflows, manage inspection dispatch and verification, and view analytics and reports.</td>
              </tr>
              <tr>
                <td><strong>Inspector</strong></td>
                <td>Use the field app to view assigned work and submit field findings. Inspectors do not sign in to the web Admin portal.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          Some actions are restricted even within the web portal. For example,
          only Super Admin can create or manage accounts; API quota and testing
          controls are for administrators.
        </p>
      </>
    ),
  },
  {
    id: "registry",
    number: "3",
    title: "Business Registry",
    badge: "Registry",
    content: (
      <>
        <p>
          The Registry is the official business information used when reviewing
          map findings. Import the latest approved records before running a
          detection scan.
        </p>
        <h4>Find and review a business</h4>
        <ol>
          <li>Open <strong>Registry</strong> from the navigation.</li>
          <li>Search by business name, ID, type, or address. Use the available filters to narrow the list.</li>
          <li>Select a row to view its details. Administrators can edit or delete records when those actions are available.</li>
          <li>Use <strong>Export CSV</strong> to download the registry records in the current result set.</li>
        </ol>
        <h4>Upload or import records</h4>
        <ol>
          <li>Prepare a CSV or Excel file (.csv, .xlsx, or .xls) with business names, permit IDs, barangays, and other available business details.</li>
          <li>Choose <strong>Upload File</strong> to add a file, or <strong>Import</strong> to bring in and synchronize records from a file.</li>
          <li>Review the import summary and any rows that need correction before relying on the updated registry.</li>
        </ol>
        <div className="manual-callout manual-callout--warning">
          The upload screen enforces a maximum batch size of 1,500 records.
          Missing or unrecognized required data may cause rows to be skipped.
          Use the error summary to correct the source file and try again.
        </div>
      </>
    ),
  },
  {
    id: "map",
    number: "4",
    title: "Map & Flags",
    badge: "Map workflows",
    content: (
      <>
        <p>
          Map &amp; Flags displays registry businesses and map findings. Select
          a marker to review its available details. Use the map filters and
          layers to focus on the information you need.
        </p>
        <h4>Run Detection</h4>
        <ol>
          <li>Confirm the official business registry is populated and current.</li>
          <li>On the Map &amp; Flags page, choose <strong>Quick Discovery</strong> or <strong>Full Coverage</strong> if prompted.</li>
          <li>Select <strong>Run Detection</strong> and review the scan and usage confirmation before proceeding.</li>
          <li>Wait for the progress and result message. If an application usage limit is reached, the scan may pause with incomplete work available to resume later.</li>
        </ol>
        <p>
          Detection compares map listings with registry records. A possible
          mismatch is a lead for review, not a final finding; verify the
          business details and available evidence before taking action.
        </p>
        <h4>Business and map-pin matching</h4>
        <p>
          REVELA compares business names and other available details when
          linking a map listing to a registry record. A confident match can be
          placed automatically. A possible but uncertain match is marked for
          Admin review; location or address alone does not prove that two
          records are the same business.
        </p>
        <ol>
          <li>Open <strong>Review Pin Suggestions</strong> or select <strong>Review suggested location</strong> on a business that needs review.</li>
          <li>Compare the suggested place with the registered business details.</li>
          <li>Select <strong>Approve move</strong> only when the place is the same business. Select <strong>Reject suggestion</strong> when it is not.</li>
        </ol>
        <p>
          Manual and approved map locations are protected from automatic
          movement. Flag color describes the business or compliance status;
          match status describes how its map location was matched.
        </p>
        <h4>Flag colors</h4>
        <div className="manual-table-wrap">
          <table>
            <thead><tr><th>Color</th><th>Meaning shown in REVELA</th></tr></thead>
            <tbody>
              <tr><td>Green</td><td>Active business</td></tr>
              <tr><td>Yellow</td><td>Suspected unregistered business; yellow findings may be reported from the field</td></tr>
              <tr><td>Red</td><td>Detected unregistered business</td></tr>
              <tr><td>Orange</td><td>Warning or notice status</td></tr>
              <tr><td>Purple</td><td>Closed or abandoned</td></tr>
              <tr><td>Black</td><td>Blacklisted or non-responsive</td></tr>
              <tr><td>Blue</td><td>In inspection / dispatched filter indicator</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          Colors summarize the current status. They do not replace checking the
          business record or inspection history.
        </p>
        <h4>Other map actions</h4>
        <ul>
          <li><strong>Add Flag:</strong> An administrator can record a map finding and its location.</li>
          <li><strong>Reconcile:</strong> Re-check red findings against the registry and correct mismatches where supported.</li>
          <li><strong>Snap Pins:</strong> Find map locations for registered businesses that do not yet have coordinates.</li>
          <li><strong>Re-verify Pins:</strong> Check selected existing pins that may be misplaced. Review uncertain suggestions before approving or rejecting a move.</li>
        </ul>
        <div className="manual-callout manual-callout--info">
          Detection and map lookup actions are subject to application limits.
          Before starting, review the remaining scans and request budgets shown
          in the confirmation or API Usage &amp; Limits modal.
        </div>
      </>
    ),
  },
  {
    id: "inspections",
    number: "5",
    title: "Inspections and field work",
    badge: "Dispatch",
    content: (
      <>
        <p>
          The Inspections page tracks assignments through four stages:
          <strong> Assigned → Reassigned → Submitted → Verified</strong>.
          Admins see the full dispatch board; Inspectors work from their
          assigned tasks in the field app.
        </p>
        <h4>For Admins</h4>
        <ol>
          <li>Open <strong>Inspections</strong> and find the business or flag that needs a visit.</li>
          <li>Assign an Inspector and set a due date. Use the Calendar View to review scheduled work.</li>
          <li>When a report is submitted, open it and review the Inspector’s notes, result, and evidence.</li>
          <li>Select <strong>Verify</strong> to accept the report, or <strong>Send back</strong> to reassign it with corrective instructions.</li>
          <li>Use <strong>Follow-up</strong> when a verified case needs another compliance visit.</li>
        </ol>
        <h4>For Inspectors</h4>
        <ol>
          <li>Open the assigned task in the field app and confirm the business and location.</li>
          <li>Record the result, add observations, and capture the requested evidence.</li>
          <li>Review the report and submit it. If there is no connection, keep it queued on the device and sync when online.</li>
          <li>If you find a business missing from the registry, use the field app’s report-finding action to submit it for Admin review.</li>
        </ol>
        <p>
          A report marked Reassigned needs another visit or corrected
          information. Follow the Admin’s notes and submit the updated report.
        </p>
      </>
    ),
  },
  {
    id: "analytics-reports",
    number: "6",
    title: "Analytics and reports",
    badge: "Reports",
    content: (
      <>
        <p>
          Use <strong>Analytics</strong> to review system summaries and charts.
          Apply the available filters, then select <strong>Refresh</strong> to
          load the latest view.
        </p>
        <p>
          Open <strong>Export Reports</strong> for demographic and operational
          reports. Depending on the report, available outputs include CSV,
          chart images (PNG), or PDF. Use the export buttons on the report or
          chart you need and save the generated file.
        </p>
        <div className="manual-callout manual-callout--info">
          Reports describe the records and field submissions currently
          available in REVELA. Check the selected filters and reporting period
          before sharing an exported file.
        </div>
      </>
    ),
  },
  {
    id: "api-usage",
    number: "7",
    title: "API Usage & Limits",
    badge: "Administrator",
    content: (
      <>
        <p>
          Admins open <strong>API Usage &amp; Limits</strong> from{" "}
          <strong>More Actions</strong> on the Map &amp; Flags page. The window
          summarizes tracked requests, the remaining allowance for each lookup
          type, Run Detection scans left, and any warnings.
        </p>
        <ul>
          <li>Usage is shared across Admin and Super Admin accounts; one administrator’s requests reduce the allowance shown to the others.</li>
          <li>Each lookup type has its own allowance: <strong>Business Lookup</strong>, <strong>Map Pin Refresh</strong>, <strong>Run Detection Requests</strong>, and <strong>Address Lookup</strong>. What is left for one type is never used by another.</li>
          <li>A warning appears as soon as a type reaches 80% of a daily or monthly limit, and again when the limit is reached.</li>
          <li>These counts are tracked internally by REVELA for application limits. They are not Google Cloud billing figures.</li>
          <li><strong>Advanced Settings</strong> is collapsed by default and available to Super Admins only. It holds application limits, Business Lookup workflow allocations, Test Mode, fixture management, and the technical quota detail.</li>
          <li>Test Mode affects testing behavior. Check its active indicator before using the system for normal operations.</li>
        </ul>
      </>
    ),
  },
  {
    id: "accounts-security",
    number: "8",
    title: "Accounts, login, and session safety",
    badge: "Security",
    content: (
      <>
        <h4>Manage user accounts (Super Admin only)</h4>
        <ol>
          <li>Open <strong>User Management</strong>.</li>
          <li>Select <strong>Create User</strong> to add an Admin or Inspector account, or use the row’s edit action to update an account.</li>
          <li>Use the search and role filters to find accounts. Follow the on-screen prompts to complete changes.</li>
        </ol>
        <p>Only a Super Admin can access the User Management page.</p>
        <h4>Login and password help</h4>
        <ul>
          <li>Enter your authorized username or email and password on the sign-in page.</li>
          <li>If 2-step verification is enabled for your account, enter the code requested by the sign-in screen.</li>
          <li>Use <strong>Forgot password?</strong> and follow the account verification steps if you cannot sign in.</li>
          <li>If asked to change a temporary password, set and confirm a new password before continuing.</li>
        </ul>
        <h4>Inactivity and sign-in restrictions</h4>
        <p>
          The portal warns after 9 minutes without activity and signs you out
          after 10 minutes. Use the page or respond to the warning to continue
          working. Background updates do not count as activity. A session
          replaced by another sign-in may also require you to sign in again.
        </p>
        <div className="manual-callout manual-callout--warning">
          Do not share accounts or passwords. Sign out when leaving a shared
          workstation, and keep exported business and inspection records
          restricted to authorized staff.
        </div>
      </>
    ),
  },
];

export default function InstructionalManualModal({
  initialSectionId = "overview",
  onClose,
  isClosing,
}) {
  const [activeSectionId, setActiveSectionId] = useState(initialSectionId);
  const [searchQuery, setSearchQuery] = useState("");

  const filteredSections = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return manualSections;
    return manualSections.filter((section) =>
      `${section.title} ${section.badge} ${section.number}`.toLowerCase().includes(query),
    );
  }, [searchQuery]);

  const activeSection = manualSections.find(
    (section) => section.id === activeSectionId,
  ) ?? manualSections[0];

  return createPortal(
    <div
      className={`modal-backdrop instructional-manual-backdrop${isClosing ? " closing" : ""}`}
      onClick={onClose}
    >
      <section
        className={`modal-panel instructional-manual-panel${isClosing ? " closing" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="instructional-manual-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="instructional-manual-header">
          <div className="instructional-manual-brand">
            <img src={municipalSeal} alt="Mataasnakahoy seal" />
            <div>
              <h2 id="instructional-manual-title">REVELA User Guide</h2>
              <p>BPLO · Municipality of Mataasnakahoy, Batangas</p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close manual">
            ×
          </button>
        </header>

        <div className="instructional-manual-layout">
          <nav className="instructional-manual-sidebar" aria-label="Manual sections">
            <label className="instructional-manual-search">
              <span className="sr-only">Search manual sections</span>
              <input
                type="search"
                placeholder="Search this guide…"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </label>
            <div className="instructional-manual-section-list">
              {filteredSections.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className={section.id === activeSection.id ? "active" : ""}
                  onClick={() => setActiveSectionId(section.id)}
                  aria-current={section.id === activeSection.id ? "page" : undefined}
                >
                  <span>SECTION {section.number} · {section.badge}</span>
                  <strong>{section.title}</strong>
                </button>
              ))}
              {filteredSections.length === 0 && (
                <p className="instructional-manual-empty">No matching sections.</p>
              )}
            </div>
          </nav>

          <article className="instructional-manual-reader">
            <div className="instructional-manual-reader-heading">
              <span>SECTION {activeSection.number} · {activeSection.badge}</span>
              <h3>{activeSection.title}</h3>
            </div>
            <div className="instructional-manual-copy">{activeSection.content}</div>
          </article>
        </div>

        <footer className="instructional-manual-footer">
          <span>REVELA · BPLO Mataasnakahoy</span>
          <button type="button" className="ghost-btn" onClick={onClose}>Close guide</button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
