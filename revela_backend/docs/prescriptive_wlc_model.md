# Prescriptive inspection priority — WLC v3

The purpose is to decide **which barangay should be inspected first**, using one
Weighted Linear Combination (WLC) model. Analytics, Overview, Map dispatch and
dispatch exports use the same scoring implementation in `api/analytics/scoring.py`.

## Inputs and formula

- Only eligible geospatial Red/Yellow/Black records enter the inspection workload.
  Eligibility preserves the existing mapped/reported/inspected-pin predicate.
  Counts are distinct `logID`s, **not unique establishments**; separate records can
  refer to the same establishment. Green, Orange and Purple do not enter WLC.
- `burden = 3*Red + 2*Yellow + 4*Black`.
- `risk = 100*burden / maximum municipal burden`; zero when the maximum is zero.
  Normalizing by weighted burden fixes premature saturation at 100.
- Distance is Haversine distance (Earth radius 6371.0088 km) from BPLO to the
  mean paired, valid coordinates of dispatchable Red/Yellow records only. It is not road
  distance or travel time. `proximity = 100 - min(100, distance_km/20*100)`.
  Missing coordinates use neutral proximity 50 and are disclosed in the response.
- `OPS = w1*risk + w2*sector + w3*proximity`, rounded to one decimal. Component
  scores are rounded to one decimal before WLC so the returned inputs reproduce
  OPS. Zero active flags always means OPS 0, regardless of the other inputs.
- Shipped policy: **68% Risk / 7% Sector / 25% Proximity**, as established by
  the project's stakeholder interviews. Scoring applies these weights unchanged;
  correctness fixes do not recalibrate the interview-derived policy.
- Existing sector overrides and the original neutral fallback of **50** are
  preserved. A missing or constant sector input does **not** disable the sector
  criterion, zero its weight, or redistribute its weight to other criteria.
  The neutral fallback contributes `0.07*50 = 3.5` points under the default policy;
  it is not a measured industry-risk score. Input coverage and fallback use are
  disclosed separately from the configured weights. Only explicit admin edits
  change saved weights; Use Default/Reset restores 68/7/25.
- PSIC display-sector scores are editable integer policy inputs in Settings.
  Their persisted numeric policy version increments on each save or reset, and
  the audit history records the actor, timestamp, complete old values, complete
  new values, and resulting version. The unclassified fallback remains fixed at
  50. Policy scores are administrative priorities, not empirically measured
  industry risk.

Scores and ranks always use the full current municipal cohort. Barangay filters
only hide rows after scoring and allocation; they never renormalize or renumber
the remaining rows. Registry, flag, detection-date and inspection filters apply
to other analytics but **not** this operational model. There is no implicit
filtered-scenario mode. The API reports ignored filters.

Higher OPS comes first. Rounded-score ties use weighted burden, then barangay
name and ID, for deterministic results. High priority starts at 60, Standard at
30, and Monitor is below 30; the same bands drive dispatch and the priority
table. These are explicit policy bands, not violation probabilities. They have
not been statistically recalibrated against inspection outcomes. Because the
reference is the current maximum, scores are not a fixed historical risk scale.

## Inspector allocation

Available means active Inspector accounts without an open Assigned, Reassigned
or In Progress report. Submitted/Verified work does not occupy a field slot.
The application has no shift/leave roster, so staff must confirm actual field
availability. The existing six-inspector plan cap remains.

Take the first three WLC-ranked barangays with dispatchable Red/Yellow targets.
Black records remain in severity context, but the existing dispatch guard
prohibits new Black inspections. Targets with Assigned/Reassigned/In Progress
reports are also ineligible for a new plan. The full table retains municipal
WLC ranks and labels Black-only/fully assigned barangays; Map and Overview field
queues skip them. With fewer free
inspectors than destinations, cover the highest-ranked destinations first and
mark the rest deferred. Give each selected destination one inspector. Allocate
remaining slots by **dispatchable** weighted burden (3*Red + 2*Yellow), using integer quotas and largest remainders;
ties follow WLC order. Never allocate negative/fractional inspectors or more than
the available capped pool. Zero available inspectors means zero deployments,
not a fabricated six-person workforce. Deferred plans have no promised date.
This is a recommendation, not an automatic assignment or an authorization to
override Black-lock dispatch guards.

## Registry context, not an OPS input

`registry_active_flag_rate` counts unique current Red/Yellow/Black **registry
businesses**, including those without mapped records, divided by the same full
registry population in that barangay. It uses canonical registry/enforcement
state, not counts of joined pins. Zero denominator returns `null` (N/A).
`unregistered_candidate_count` is a separate count of Red geospatial records
with no registry identity match using the shared ID/place/name matching rules.
Neither metric is a confirmed-violation rate. The old mixed-population
`non_compliance_rate` field and silently clipped radar percentage are removed.

Weights must be finite numbers within 0–100 totaling 100. Coordinates and sector
overrides are also validated. Valid saved weights are never re-normalized at runtime.
Invalid updates return HTTP 400 without writing to disk or replacing the cache.

## Verification

Regression tests cover risk discrimination, severity ordering, deterministic
ties, zero flags, missing/invalid coordinates, sector coverage, registry rates,
display-filter invariance, Analytics/Map parity, invalid configuration and
workforce shortages. SQL integration tests use the existing in-memory SQLite
adapter; they do not claim a MySQL runtime/EXPLAIN benchmark. The candidate split
aggregate remains default-off. No live data or Google requests are needed.
