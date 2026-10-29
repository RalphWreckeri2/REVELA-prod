export const SECTOR_RISK_DEFAULTS = Object.freeze({
  version: "psic-sector-risk-v1",
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
      throw new Error(`${label} must be a number from 0 to 100.`);
    }
    const value = Number(score);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      throw new Error(`${label} must be a number from 0 to 100.`);
    }
    return value;
  };

  return {
    fallback_score: normalizeScore(policy.fallback_score, "Fallback score"),
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
