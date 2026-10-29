import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  normalizeSectorRiskPolicy,
  SECTOR_RISK_CATEGORIES,
  SECTOR_RISK_DEFAULTS,
  sectorRiskPolicySignature,
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
});

test("sector policy signatures compare normalized numeric drafts", () => {
  const saved = normalizeSectorRiskPolicy(SECTOR_RISK_DEFAULTS);
  const draft = {
    fallback_score: "50",
    categories: { ...saved.categories, Retail: "80" },
  };
  assert.equal(sectorRiskPolicySignature(saved), sectorRiskPolicySignature(draft));
});

test("Settings exposes editable sector scores and save/reset actions", () => {
  assert.match(settingsSource, /Sector Risk Weights/);
  assert.match(settingsSource, /SECTOR_RISK_CATEGORIES\.map/);
  assert.match(settingsSource, /type="range"[\s\S]*?type="number"/);
  assert.match(settingsSource, /Save Sector Risk Policy/);
  assert.match(settingsSource, /Reset to Defaults/);
  assert.match(settingsSource, /revela:policy-update/);
  assert.match(settingsSource, /sectorPolicy:\s*saved/);
  assert.match(settingsStyles, /\.settings-sector-policy-row\s*\{/);
  assert.match(settingsStyles, /@media \(max-width: 640px\)/);
  assert.match(refreshProviderSource, /"policy-update":\s*\["home", "map", "analytics", "settings"\]/);
  assert.match(refreshProviderSource, /coordinator\.invalidate\(views\)/);
});

test("sector risk policy API exposes authenticated load, update, and reset calls", () => {
  assert.match(apiSource, /getSectorRiskPolicyRequest/);
  assert.match(apiSource, /updateSectorRiskPolicyRequest/);
  assert.match(apiSource, /resetSectorRiskPolicyRequest/);
  assert.match(apiSource, /\/analytics\/sector-policy\/reset/);
});
