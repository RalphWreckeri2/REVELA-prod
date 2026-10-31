export const SECTOR_RISK_DEFAULTS = Object.freeze({
  version: 1,
  fallback_score: 50,
  categories: Object.freeze({
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
  }),
});

export const SECTOR_RISK_CATEGORIES = Object.keys(SECTOR_RISK_DEFAULTS.categories);

export function getSectorRiskPolicyCoverage(rankings) {
  if (!Array.isArray(rankings)) return null;

  let total = 0;
  let withSector = 0;
  for (const ranking of rankings) {
    const entityCount = ranking?.sector_entity_count;
    const knownCount = ranking?.sector_known_entity_count;
    if (!Number.isInteger(entityCount) || entityCount < 0
        || !Number.isInteger(knownCount) || knownCount < 0 || knownCount > entityCount) {
      return null;
    }
    total += entityCount;
    withSector += knownCount;
  }
  return { withSector, total };
}

export function sectorRiskPolicyPreviewHasChanges(preview) {
  return Boolean(preview?.rows?.some(row => (
    row.old_ops !== row.new_ops || row.old_rank !== row.new_rank
  )));
}

export function normalizeSectorRiskPolicy(policy) {
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) {
    throw new Error("Sector risk policy must be an object.");
  }
  if (Object.keys(policy).some(key => !["version", "fallback_score", "categories"].includes(key))) {
    throw new Error("Sector risk policy contains an unknown field.");
  }
  if (!policy.categories || typeof policy.categories !== "object" || Array.isArray(policy.categories)
      || SECTOR_RISK_CATEGORIES.some(category => !Object.hasOwn(policy.categories, category))
      || Object.keys(policy.categories).length !== SECTOR_RISK_CATEGORIES.length) {
    throw new Error("Sector risk policy must include all 12 PSIC categories.");
  }

  const normalizeScore = (score, label) => {
    if ((typeof score !== "number" && typeof score !== "string")
        || (typeof score === "string" && !score.trim())) {
      throw new Error(`${label} must be an integer from 0 to 100.`);
    }
    const value = Number(score);
    if (!Number.isInteger(value) || value < 0 || value > 100) {
      throw new Error(`${label} must be an integer from 0 to 100.`);
    }
    return value;
  };
  const version = policy.version ?? SECTOR_RISK_DEFAULTS.version;
  if (!Number.isInteger(version) || version < 1) {
    throw new Error("Policy version must be a positive integer.");
  }
  const fallbackScore = normalizeScore(policy.fallback_score, "Fallback score");
  if (fallbackScore !== 50) {
    throw new Error("The unclassified fallback score is fixed at 50.");
  }

  return {
    version,
    fallback_score: fallbackScore,
    categories: Object.fromEntries(SECTOR_RISK_CATEGORIES.map(category => [
      category,
      normalizeScore(policy.categories[category], category),
    ])),
  };
}

export function sectorRiskPolicySignature(policy) {
  try {
    const normalized = normalizeSectorRiskPolicy(policy);
    return JSON.stringify(normalized);
  } catch {
    return "";
  }
}

export function normalizeSectorRiskPreview(preview) {
  if (!preview || typeof preview !== "object" || Array.isArray(preview)) {
    throw new Error("Policy preview must be an object.");
  }
  const { current_version: currentVersion, proposed_version: proposedVersion, rows } = preview;
  if (!Number.isInteger(currentVersion) || currentVersion < 1
      || proposedVersion !== currentVersion + 1
      || !Array.isArray(rows) || rows.length > 16) {
    throw new Error("Policy preview response is invalid.");
  }
  const normalizedRows = rows.map(row => {
    if (!row || typeof row !== "object"
        || !Number.isInteger(row.barangayID)
        || typeof row.barangayName !== "string"
        || !Number.isInteger(row.old_rank) || row.old_rank < 1
        || !Number.isInteger(row.new_rank) || row.new_rank < 1
        || !Number.isFinite(row.old_ops) || row.old_ops < 0 || row.old_ops > 100
        || !Number.isFinite(row.new_ops) || row.new_ops < 0 || row.new_ops > 100) {
      throw new Error("Policy preview contains an invalid ranking row.");
    }
    return row;
  });
  return {
    current_version: currentVersion,
    proposed_version: proposedVersion,
    model_version: typeof preview.model_version === "string" ? preview.model_version : "",
    rows: normalizedRows,
  };
}
