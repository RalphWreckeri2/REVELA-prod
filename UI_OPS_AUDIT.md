# UI and OPS allocation audit

Audit date: 2026-10-31. Findings refer to the current local source.

## Inspector allocation: result

The current allocator preserves the expected first-pass coverage:

| Reproduced input | Allocation across three eligible barangays |
| --- | --- |
| Two active inspectors, both free | `[1, 1, 0]` |
| Two active inspectors, one with an Assigned report | `[1, 0, 0]` |

These results were reproduced using the real workforce SQL against an in-memory database and the actual recommendation generator. The browser also rendered the corresponding recommendations correctly with synthetic API responses.

**Two inspector accounts do not necessarily mean two available inspectors.** `Assigned`, `Reassigned`, and `In Progress` reports exclude an active inspector from this planning pool. `Submitted` and `Verified` do not. Each eligible destination first receives one inspector, before extra staff are distributed. Allocations cover at most three eligible barangays and six inspectors, capped by eligible business count.

Sources:
- `revela_backend/api/analytics/routes.py:1800` — workforce availability SQL.
- `revela_backend/api/analytics/routes.py:1877` — workforce and allocation response.
- `revela_backend/api/analytics/dispatch.py:127` — limits and destination eligibility.
- `revela_backend/api/analytics/dispatch.py:145` — one inspector per selected destination before extras.

The reported live case is **consistent with one inspector already being busy**, but that inspector's actual assignment state was not available in this local audit. If the live response says `available_inspectors: 2` and at least two eligible destinations exist, `[1, 0, ...]` would contradict the reproduced current behavior. Check that response, the selected barangay filter, and the deployed revision before changing the allocation formula.

## Fix queue

OPS-01 is fixed in the local source; the remaining items are open. IDs are stable so fixes can be discussed one at a time.

### OPS-01 — Explain why two accounts become one available inspector

**Priority: P1 — allocation transparency. Browser-confirmed.**

**Status: Fixed locally, 2026-10-31.**

- Original finding: the visible recommendation header showed only the available count. Active count, allocation summary, and availability rules were inside a block disabled by `ADMIN_PRESCRIPTIVE_DETAILS_ENABLED = false`.
- Original reproduction: API returned two active and one available; the screen said “1 inspector available” without explaining the missing inspector.
- Implemented: the main Recommendations screen now shows Active, Busy with open reports, Available for recommendations, and Recommended in municipal plan together. Busy is the difference between the API's active and available counts. The open-report rule is visible, with full availability, allocation-cap, and municipality-wide filtering rules accessible beside the counts.
- Rows now say “1 inspector recommended” under “Recommended staffing”; the header explains that assignments are created separately in Map & Flags. The loading skeleton includes the same summary layout.
- Sources: `revela_web/src/pages/AnalyticsPage.jsx` (workforce derivation and visible recommendation summary); `revela_web/src/components/analyticsPresentation.js:111`; `revela_web/src/components/AnalyticsLoadingLayouts.jsx:88`; `revela_web/src/styles/AnalyticsPage.css`.

Post-fix verification:
- All 24 existing prescriptive scoring/allocation tests passed. Six focused recommendation-presentation/loading tests, targeted ESLint, and the production build passed.
- Ten in-memory cases passed using the actual workforce SQL, section builder, and allocator with supplied ranked inputs: two free, Assigned (including duplicate reports for one inspector), Reassigned, In Progress, Submitted, Verified, both busy, one inactive, limited eligible targets, and a barangay-filtered view.
- The actual React screen passed 25 headless Edge runs using those generated responses plus a missing-workforce response. Light/dark modes at widths 1440, 1280, 1024, and 768 preserved counts and staffing labels; the availability tooltip remained keyboard-accessible and inside the viewport. No page-level horizontal overflow or uncaught JavaScript exceptions occurred.
- Temporary reproduction scripts/screenshots: `%LOCALAPPDATA%/Temp/opencode/revela-inspector-availability-check.py`, `revela-inspector-availability-check.mjs`, and `revela-inspector-availability-{light,dark}.png`.

### OPS-02 — Different exclusions collapse into “Not scheduled yet”

**Priority: P1 — misleading dispatch state. Browser-confirmed.**

- A row without a dispatch recommendation receives “Not scheduled yet”, whether it is Black-only, fully assigned already, or outside the top-three eligible plan.
- Expanded content only says “No dispatch allocation is available for this barangay.”
- Black-only rows can retain high priority while the reason shows Red 0 / Yellow 0: Black count and administrative-review guidance are absent from that reason.
- Suggested fix: display a specific reason such as “Administrative review — Black only”, “Targets already assigned”, or “Outside current top-three plan”. Keep these distinct from a genuinely deferred plan waiting for staff.
- Sources: `revela_web/src/components/analyticsPresentation.js:98`, `:111`; `revela_web/src/pages/AnalyticsPage.jsx:2308`; `revela_backend/api/analytics/dispatch.py:129`.

### OPS-03 — Plans allocate staff to targets the dispatch UI blocks for missing coordinates

**Priority: P1 — recommendation/dispatch eligibility mismatch. SQL reproduction confirmed.**

- Recommendation eligibility counts Red/Yellow targets without requiring valid coordinates. Coordinate validation is applied to the location average, not the dispatchable counts/business count.
- Map/Batch Dispatch eligibility explicitly blocks records without an exact location.
- Reproduction: one unassigned Red record with a place ID and null latitude/longitude produces `dispatchable_count: 1`, `dispatchable_business_count: 1`, `location_missing: true`, and a one-inspector deployment recommendation.
- Suggested fix: align planning capacity with actual dispatch eligibility. Missing-location records can retain risk context and a location-resolution action, without consuming a field allocation.
- Sources: `revela_backend/api/analytics/routes.py:1561`, `:1578`, `:1588`; `revela_web/src/components/dispatchEligibility.js:51`; `revela_web/src/components/BatchDispatchModal.jsx:75`.

### UI-01 — Settings selected toggles have white text on bright mint

**Priority: P2 — dark-mode legibility. Browser-confirmed.**

- Selected Email On/Off and Appearance buttons use white text on `--color-primary`.
- In dark mode, that background becomes `#34d399`; measured text contrast is approximately **1.92:1** at 13px. The shared primary-button dark treatment uses dark text, but these inline controls do not inherit it.
- Light-mode selected toggles also measure approximately 2.89:1.
- Suggested fix: use a shared selected-control foreground/background pair that adapts to the theme.
- Sources: `revela_web/src/pages/SettingsPage.jsx:954`, `:1025`; `revela_web/src/styles/global.css:1324`, `:1604`.

### UI-02 — Registry Business IDs are too dark; active pagination also loses contrast

**Priority: P2 — reading and navigation. Browser-confirmed.**

- Business ID cells hard-code `#475569`, overriding the dark table text. Measured contrast is approximately **2.43–2.53:1** on the dark rows.
- The active page-number button keeps white text on mint: approximately **1.92:1**.
- Suggested fix: use theme-aware ID text and selected-pagination colors.
- Sources: `revela_web/src/pages/RegistryPage.jsx:783`, `:967`.

### UI-03 — Deadline calendar icon stays black in a dark inspection dialog

**Priority: P2 — discoverability of date control. Browser/screenshot-confirmed in Edge.**

- Open Inspection Details, then Reassign. The Deadline field has a dark background but its native calendar icon stays nearly black.
- Computed `color-scheme` is `normal`; the calendar-indicator filter is `none`. The global dark form rules change CSS colors without opting native controls into dark mode.
- Suggested fix: apply appropriate `color-scheme` to the relevant dark form controls/dialog and verify the native picker. Audit the equivalent Map and Batch Dispatch deadline fields with the same treatment.
- Sources: `revela_web/src/pages/InspectionPage.jsx:318`; `revela_web/src/styles/global.css:1664`; `revela_web/src/styles/InspectionDialog.css:14`.

### UI-04 — Reports export controls and section badges have inconsistent dark colors

**Priority: P2 — chart action legibility. Browser-confirmed with populated report fixtures.**

- Enabled Export PNG buttons keep dark blue `#2563eb` on a dark blue-tinted surface: approximately **3.43:1** at 11.5px.
- Section 1 uses white on mint: approximately **1.92:1**. Section 2 uses white on blue: approximately 3.68:1.
- Operational tags such as Field Enforcement and WLC Operational Priority retain hard-coded light fills in dark mode.
- Suggested fix: theme-aware chart-action, section-badge, and operational-tag styles for the on-screen page.
- Sources: `revela_web/src/pages/ExportReportsPage.jsx:198`, `:210`, `:1049`, `:1651`, `:2240`.

### UI-05 — Recommendation High Priority text bypasses the dark indigo token

**Priority: P3 — small-text contrast. Browser-confirmed.**

- Priority labels use the API's fixed `#6366f1` inline color, even though the page defines a lighter dark-mode indigo token.
- Measured contrast: approximately **4.35:1** at 12px against `#0d0d0d`, slightly below the 4.5:1 normal-text target.
- Suggested fix: map priority levels to theme-aware presentation colors.
- Sources: `revela_backend/api/analytics/scoring.py:28`; `revela_web/src/pages/AnalyticsPage.jsx:2264`; `revela_web/src/styles/AnalyticsPage.css:32`.

### UI-06 — Calendar Today number has weak contrast

**Priority: P3 — small-text contrast. Browser-confirmed.**

- Today's white number on dark-mode primary-dark green `#059669` measures approximately **3.77:1**. The mini-calendar number is 11px.
- Suggested fix: use a dedicated Today foreground/background pair that remains readable in both themes.
- Sources: `revela_web/src/styles/global.css:1325`, `:3459`, `:3736`.

### UI-07 — User avatar initials have low contrast on some palette colors

**Priority: P3 — both themes. Browser-confirmed.**

- Small white initials measure approximately **2.89:1** on green `#56ab2f` and **3.68:1** on blue `#3b82f6`.
- Suggested fix: select a suitable foreground per avatar fill, or darken the affected fills.
- Sources: `revela_web/src/pages/UserManagementPage.jsx:39`; `revela_web/src/styles/UserManagement.css:63`.

## Verification notes

- Local headless Edge ran the actual React screens with synthetic API responses: Recommendations, Settings, Registry, User Management, Inspection Dispatch/Reassign, Inspection Calendar, Analytics Overview, and Reports. Reports were also reviewed with the existing populated layout fixture.
- Recommendations were checked at desktop viewport widths 1440, 1280, 1024, and 768. No page-level horizontal overflow was observed in those checks.
- Browser runs recorded no uncaught JavaScript exceptions. Contrast measurements are CSS-color measurements; screenshot review also confirmed the dark Business IDs and native deadline icon.
- Backend command using `revela_backend/venv/Scripts/python.exe`: `-m unittest discover -s tests -p "test_prescriptive*.py" -v`. **42 tests: 30 passed, 12 errored.** All 24 scoring/allocation tests passed. The 12 query errors share the SQLite harness failure `near "USING": syntax error` while processing MySQL `CONVERT(... USING utf8mb4)` in sector SQL. This does not establish a production MySQL failure. The allocation scenarios above were therefore also checked independently with the actual workforce SQL and generator.
- Frontend command: `node --test src/components/analyticsPresentation.test.js src/components/dispatchEligibility.test.js`. **31 tests: 29 passed, 2 failed.** Failures are source-shape assertions: an expected exact loading-status markup match is absent from the current page source, and a rule-count assertion expects two shared grid declarations where the current skeleton adds a third. Allocation wording/order and dispatch-eligibility behavior tests passed.
- Temporary audit results/screenshots: `%LOCALAPPDATA%/Temp/opencode/revela-ui-audit-results.json`, `revela-ui-audit-followup.json`, and `revela-audit-*.png`.

Suggested sequence: **OPS-01 -> OPS-02 -> OPS-03 -> UI-01 -> UI-02 -> UI-03 -> UI-04 -> UI-05 -> UI-06 -> UI-07.**
