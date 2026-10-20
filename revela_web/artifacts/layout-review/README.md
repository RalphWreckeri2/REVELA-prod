# Analytics and Export Reports — visual review

Run `npm run test:layouts:browser` from `revela_web` to regenerate the screenshots
and `results.json`. Uses the installed Microsoft Edge in headless mode, a fresh
browser profile, 100% zoom, and synthetic API responses rendered through the real
application routes. No production credentials or records are used.

The matrix covers 768 × 1024, 1024 × 768, 1280 × 800, and 1440 × 1000 with both
sidebar preferences. At 768 px navigation is a drawer; its open/closed states are
also checked. Screenshots preserve the actual viewport, scroll position, and
browser zoom; they are not scaled-down full-page composites.

Additional cases cover populated charts and long labels, loading, empty and
failed requests, tab changes, resizing/sidebar toggles, tooltips, PNG download,
print/PDF preparation, tablet login, and the phone restriction.

## Result

- **48 browser scenarios passed**, with no Recharts dimension warnings or browser
  exceptions. Loading, empty, and error states were checked at all four widths.
- Lint, production build, context verification, and **196 available frontend
  tests** passed. The existing analytics browser smoke check passed all 10 checks.
- Backend auth/session and device-policy parity checks: **33 tests passed**,
  including 42 parameterized subtests.
- The aggregate `npm run verify` stops at a pre-existing missing test file:
  `src/components/mapMarkerPosition.test.js`. Its remaining available suites
  and the production build were run separately and passed.

## Selected screenshots

- [1440 px desktop — paired Analytics cards](analytics-1440-expanded-paired.png)
- [1440 px collapsed sidebar — Compliance Timeline](analytics-1440-collapsed-timeline.png)
- [1280 px laptop — donut legends below charts](analytics-1280-expanded-paired.png)
- [768 px tablet portrait — Geographic Spread and Top Sectors](analytics-768-expanded.png)
- [1024 px tablet landscape — complete barangay labels](analytics-1024-expanded.png)
- [768 px tablet portrait — Export Reports](reports-768-expanded.png)
- [1440 px collapsed sidebar — responsive report columns](reports-1440-collapsed.png)
- [Complete long sector-name tooltip](analytics-long-sector-tooltip.png)
- [Loading](analytics-768-loading.png), [empty](analytics-1440-empty.png), and
  [error](reports-768-error.png) states
- [Tablet login without Desktop site](tablet-normal-login.png)
- [Official PDF/print preparation](reports-print-preview.png)

Geographic Spread retains columns when labels fit, and uses horizontal bars when
the available width is insufficient. Its chart stays entirely inside the card.
The 12-month Compliance Timeline retains its area series, gradients, tooltip and
legend, in a compact full-width card. Top Sectors remains a horizontal bar chart.

## Changed files

Paths below are relative to `revela_web`, except for the two backend files.

- `src/pages/AnalyticsPage.jsx`, `src/styles/AnalyticsPage.css`: requested card
  ordering, content-sized chart areas, matched pairs, responsive donut legends,
  loading/empty layouts, and the analytics controls dock.
- `src/pages/ExportReportsPage.jsx`, `src/styles/ExportReportsPage.css`: columns
  based on the content width, wrapping export toolbars, readable titles and
  legends, and responsive chart presentation.
- `src/components/ResponsiveChart.jsx`: measure positive chart dimensions before
  mounting Recharts; track sidebar, tab, and container changes.
- `src/components/GeographicBarChart.jsx`, `src/components/WrappedAxisTick.jsx`:
  adaptive geographic orientation and wrapped, tooltip-accessible axis labels.
- `src/components/DashboardLayout.jsx`: optional in-flow bottom controls slot.
- `src/components/mobileDetection.js`, `src/components/mobileDetection.test.js`:
  tablet screen/touch detection and keyboard handling; phone regressions.
- `src/services/api.js`: include physical-screen/touch hints with web login.
- `../revela_backend/api/auth/routes.py`: recognize the same tablets at the
  existing device usability gate before credential validation.
- `../revela_backend/tests/test_auth_sessions.py`: tablet credential-validation
  and phone/malformed-hint regressions.
- `src/components/analyticsCachePolicy.test.js`: resolve the API's new browser
  helper import in the existing data-URL test harness.
- `package.json`, `scripts/layout-preview.html`, `scripts/layout-preview.jsx`,
  `scripts/verify-layout-browser.mjs`: reproducible visual/browser verification.
- `artifacts/layout-review/`: screenshots, this review, and measured browser
  results in `results.json`.
