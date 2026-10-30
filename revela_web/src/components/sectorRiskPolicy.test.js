import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  normalizeSectorRiskPolicy,
  normalizeSectorRiskPreview,
  SECTOR_RISK_CATEGORIES,
  SECTOR_RISK_DEFAULTS,
  getSectorRiskPolicyCoverage,
  sectorRiskPolicySignature,
  sectorRiskPolicyPreviewHasChanges,
} from "./sectorRiskPolicy.js";

const settingsSource = readFileSync(new URL("../pages/SettingsPage.jsx", import.meta.url), "utf8");
const settingsStyles = readFileSync(new URL("../styles/SettingsPage.css", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../services/api.js", import.meta.url), "utf8");
const refreshProviderSource = readFileSync(new URL("./AppRefreshProvider.jsx", import.meta.url), "utf8");
const backendPolicyDefaults = JSON.parse(readFileSync(
  new URL("../../../revela_backend/api/analytics/sector_risk_policy.json", import.meta.url),
  "utf8",
));

test("sector policy defaults match the full 12-category score baseline", () => {
  assert.equal(SECTOR_RISK_CATEGORIES.length, 12);
  assert.deepEqual(normalizeSectorRiskPolicy(SECTOR_RISK_DEFAULTS), normalizeSectorRiskPolicy(backendPolicyDefaults));
  assert.deepEqual(normalizeSectorRiskPolicy(SECTOR_RISK_DEFAULTS), {
    version: 1,
    fallback_score: 50,
    categories: {
      Manufacturing: 90,
      "Construction and utilities": 85,
      "Wholesale and vehicles": 80,
      Retail: 80,
      "Food and drink": 75,
      "Hospitality, arts and recreation": 75,
      "Transport and storage": 70,
      "Real estate": 60,
      "Finance and professional": 50,
      "Information and communication": 50,
      "Education, health and other services": 40,
      "Agriculture and mining": 30,
    },
  });
});

test("sector policy draft validation rejects incomplete and out-of-range scores", () => {
  const valid = normalizeSectorRiskPolicy(SECTOR_RISK_DEFAULTS);
  assert.throws(() => normalizeSectorRiskPolicy({ ...valid, categories: { Retail: 80 } }), /all 12/);
  assert.throws(() => normalizeSectorRiskPolicy({
    ...valid,
    categories: { ...valid.categories, Retail: 101 },
  }), /Retail.*0 to 100/);
  assert.throws(() => normalizeSectorRiskPolicy({ ...valid, fallback_score: "" }), /Fallback.*0 to 100/);
  assert.throws(() => normalizeSectorRiskPolicy({
    ...valid,
    categories: { ...valid.categories, Retail: Number.NaN },
  }), /Retail.*0 to 100/);
  assert.throws(() => normalizeSectorRiskPolicy({
    ...valid,
    categories: { ...valid.categories, Retail: true },
  }), /Retail.*0 to 100/);
  assert.throws(() => normalizeSectorRiskPolicy({
    ...valid,
    categories: { ...valid.categories, Retail: 80.5 },
  }), /Retail.*integer/);
  assert.throws(() => normalizeSectorRiskPolicy({ ...valid, fallback_score: 51 }), /fixed at 50/);
});

test("sector policy signatures compare normalized numeric drafts", () => {
  const saved = normalizeSectorRiskPolicy(SECTOR_RISK_DEFAULTS);
  const draft = {
    fallback_score: "50",
    categories: { ...saved.categories, Retail: "80" },
  };
  assert.equal(sectorRiskPolicySignature(saved), sectorRiskPolicySignature(draft));
});

test("sector policy preview validates and preserves old/new OPS and ranks", () => {
  const preview = normalizeSectorRiskPreview({
    current_version: 4,
    proposed_version: 5,
    model_version: "wlc-v3",
    rows: [{
      barangayID: 2,
      barangayName: "Barangay II",
      old_ops: 72.1,
      old_rank: 2,
      new_ops: 75,
      new_rank: 1,
    }],
  });
  assert.equal(preview.proposed_version, 5);
  assert.equal(preview.rows[0].old_rank, 2);
  assert.equal(preview.rows[0].new_ops, 75);
  assert.throws(() => normalizeSectorRiskPreview({
    current_version: 4,
    proposed_version: 6,
    rows: [],
  }), /invalid/);
  assert.throws(() => normalizeSectorRiskPreview({
    current_version: 4,
    proposed_version: 5,
    rows: [{ barangayID: 2, barangayName: "Barangay II", old_ops: 101, old_rank: 1, new_ops: 50, new_rank: 1 }],
  }), /invalid ranking row/);
});

test("sector policy coverage reports matched entities and hides invalid counts", () => {
  assert.deepEqual(getSectorRiskPolicyCoverage([
    { sector_entity_count: 7, sector_known_entity_count: 2 },
    { sector_entity_count: 3, sector_known_entity_count: 1 },
  ]), { withSector: 3, total: 10 });
  assert.deepEqual(getSectorRiskPolicyCoverage([
    { sector_entity_count: 10, sector_known_entity_count: 0 },
  ]), { withSector: 0, total: 10 });
  assert.equal(getSectorRiskPolicyCoverage(undefined), null);
  assert.equal(getSectorRiskPolicyCoverage([
    { sector_entity_count: 2, sector_known_entity_count: 3 },
  ]), null);
});

test("sector preview change detection recognizes unchanged and changed OPS or ranks", () => {
  const unchanged = { rows: [{ old_ops: 50, new_ops: 50, old_rank: 1, new_rank: 1 }] };
  assert.equal(sectorRiskPolicyPreviewHasChanges(unchanged), false);
  assert.equal(sectorRiskPolicyPreviewHasChanges({
    rows: [{ ...unchanged.rows[0], new_rank: 2 }],
  }), true);
  assert.equal(sectorRiskPolicyPreviewHasChanges({
    rows: [{ ...unchanged.rows[0], new_ops: 50.1 }],
  }), true);
});

test("Settings exposes editable sector scores and save/reset actions", () => {
  assert.match(settingsSource, /Sector Risk Weights/);
  assert.match(settingsSource, /SECTOR_RISK_CATEGORIES\.map/);
  assert.match(settingsSource, /type="range"[\s\S]*?type="number"/);
  assert.match(settingsSource, /Save Sector Risk Policy/);
  assert.match(settingsSource, /Reset to Defaults/);
  assert.match(settingsSource, /Preview rank changes/);
  assert.match(settingsSource, /Save sector risk policy\?/);
  assert.match(settingsSource, /Unclassified fallback score/);
  assert.match(settingsSource, /getOpsRankingsRequest/);
  assert.match(settingsSource, /getSectorRiskPolicyCoverage/);
  assert.match(settingsSource, /0 of \{sectorRiskCoverage\.total\} flagged entities currently have a sector/);
  assert.match(settingsSource, /No change in ranks/);
  assert.match(settingsSource, /Policy audit history/);
  assert.match(settingsSource, /revela:policy-update/);
  assert.match(settingsSource, /sectorPolicy:\s*saved/);
  assert.match(settingsStyles, /\.settings-sector-policy-row\s*\{/);
  assert.match(settingsStyles, /@media \(max-width: 640px\)/);
  assert.match(refreshProviderSource, /"policy-update":\s*\["home", "map", "analytics", "settings"\]/);
  assert.match(refreshProviderSource, /coordinator\.invalidate\(views\)/);
});

test("sector risk policy API exposes authenticated load, update, and reset calls", () => {
  assert.match(apiSource, /getSectorRiskPolicyRequest/);
  assert.match(apiSource, /getSectorRiskPolicyAuditRequest/);
  assert.match(apiSource, /previewSectorRiskPolicyRequest/);
  assert.match(apiSource, /updateSectorRiskPolicyRequest/);
  assert.match(apiSource, /resetSectorRiskPolicyRequest/);
  assert.match(apiSource, /\/analytics\/sector-policy\/reset/);
});
