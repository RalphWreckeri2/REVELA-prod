export const API_ORIGIN =
  import.meta.env.VITE_API_ORIGIN ?? "http://127.0.0.1:5000";
const BASE_URL = `${API_ORIGIN}/api`;

/** Absolute URL for inspection evidence (relative path from API). */
export function inspectionEvidenceUrl(photoPath) {
  if (!photoPath) return null;
  const urls = inspectionEvidenceUrls(photoPath);
  return urls.length > 0 ? urls[0] : null;
}

export function inspectionEvidenceUrls(photoPath) {
  if (!photoPath) return [];
  let paths = [];
  try {
    const parsed = JSON.parse(photoPath);
    if (Array.isArray(parsed)) {
      paths = parsed;
    } else {
      paths = [photoPath];
    }
  } catch (e) {
    paths = [photoPath]; // legacy single string
  }

  const base = API_ORIGIN.replace(/\/$/, "");
  return paths.map(p => {
    if (p.startsWith("http")) return p;
    return p.startsWith("/") ? `${base}${p}` : `${base}/${p}`;
  });
}

async function handleResponse(res) {
  try {
    const data = await res.json();
    if (!res.ok) {
      const msg =
        [data.message, data.error].filter(Boolean).join(": ") ||
        `Request failed with status ${res.status}`;
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    if (err instanceof SyntaxError) {
      throw new Error(`Server error: Invalid response (${res.status})`);
    }
    throw err;
  }
}

function connectionGuard(err) {
  if (
    err.message.includes("fetch") ||
    err.message.includes("Failed to fetch")
  ) {
    throw new Error(
      "Unable to connect to server. Please check your connection.",
    );
  }
  throw err;
}

export async function loginRequest(email, password) {
  try {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    return await handleResponse(res);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error(
        "Unable to connect to server. Please check your connection.",
      );
    }
    throw err;
  }
}

export async function getMeRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/auth/me`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error(
        "Unable to connect to server. Please check your connection.",
      );
    }
    throw err;
  }
}

/** SSE URL (EventSource cannot send Authorization header reliably). */
export function getNotificationStreamUrl(token) {
  return `${API_ORIGIN}/api/notifications/stream?token=${encodeURIComponent(token)}`;
}

export async function getNotificationsRequest(token) {
  const res = await fetch(`${BASE_URL}/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return await handleResponse(res);
}

export async function getNotificationsUnreadCountRequest(token) {
  const res = await fetch(`${BASE_URL}/notifications/unread-count`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return await handleResponse(res);
}

export async function markNotificationsReadRequest(token, ids = null) {
  const body = ids && ids.length ? { ids } : {};
  const res = await fetch(`${BASE_URL}/notifications/read`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  return await handleResponse(res);
}

export async function deleteNotificationsRequest(token, ids = null) {
  const body = ids && ids.length ? { ids } : {};
  const res = await fetch(`${BASE_URL}/notifications`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  return await handleResponse(res);
}

export async function updateMePreferencesRequest(payload, token) {
  const res = await fetch(`${BASE_URL}/auth/me/preferences`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  return await handleResponse(res);
}

export async function requestOtpRequest(identifier) {
  try {
    const res = await fetch(`${BASE_URL}/auth/request-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier }),
    });
    return await handleResponse(res);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error(
        "Unable to connect to server. Please check your connection.",
      );
    }
    throw err;
  }
}

export async function resetPasswordRequest(identifier, otp, newPassword) {
  try {
    const res = await fetch(`${BASE_URL}/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier, otp, newPassword }),
    });
    return await handleResponse(res);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error(
        "Unable to connect to server. Please check your connection.",
      );
    }
    throw err;
  }
}

// ── Registry ──────────────────────────────────────────────────────────────────

/**
 * Upload a CSV or Excel file to seed the official registry.
 * @param {File} file  - the File object from the input/drop zone
 * @param {string} token - JWT token (pass explicitly from AuthContext)
 * @param {AbortSignal} signal - Optional cancellation signal
 * @returns {Promise<{total_rows, inserted, geocoded_ok, geocoded_failed, skipped, errors[]}>}
 */
export async function uploadRegistryFile(file, token, signal) {
  try {
    const form = new FormData();
    form.append("file", file);

    const res = await fetch(`${BASE_URL}/registry/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      // Do NOT set Content-Type manually — browser sets it with boundary for FormData
      body: form,
      signal,
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * Merge a CSV or Excel file into the registry (updates matching businesses by
 * name + barangay, inserts new rows). Any authenticated user may call this.
 * @returns {Promise<{total_rows, inserted, updated, geocoded_ok, geocoded_failed, skipped, errors[]}>}
 */
export async function syncRegistryFile(file, token, signal) {
  try {
    const form = new FormData();
    form.append("file", file);

    const res = await fetch(`${BASE_URL}/registry/sync`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      signal,
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

// ── Diagnostics ───────────────────────────────────────────────────────────────

export async function getDiagnosticClustersRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/geospatial/diagnostics/clusters`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await handleResponse(res);
    return data.clusters ?? data;
  } catch (err) {
    connectionGuard(err);
  }
}

// ── Reports Exports ───────────────────────────────────────────────────────────
export async function getBarangayHeatmapRequest(token, params = {}) {
  try {
    const qs = new URLSearchParams();
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    const res = await fetch(
      `${BASE_URL}/reports/barangay-heatmap?${qs.toString()}`,
      {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getSectorComplianceRequest(token, params = {}) {
  try {
    const qs = new URLSearchParams();
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    const res = await fetch(
      `${BASE_URL}/reports/sector-compliance?${qs.toString()}`,
      {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function cancelRegistryImport(token) {
  if (!token) throw new Error("Missing authentication token.");
  try {
    const res = await fetch(`${BASE_URL}/registry/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getInspectorPerformanceRequest(token, params = {}) {
  try {
    const qs = new URLSearchParams();
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    if (params.inspector_id) qs.set("inspector_id", params.inspector_id);
    const res = await fetch(
      `${BASE_URL}/reports/inspector-performance?${qs.toString()}`,
      {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * Fetch the paginated business list.
 * @param {object} params - { page, limit, search, barangayID, status }
 * @param {string} token
 */
export async function getRegistryRequest(params = {}, token) {
  try {
    const qs = new URLSearchParams();
    if (params.page) qs.set("page", params.page);
    if (params.limit) qs.set("limit", params.limit);
    if (params.search) qs.set("search", params.search);
    if (params.barangayID) qs.set("barangayID", params.barangayID);
    if (params.status) qs.set("status", params.status);

    const res = await fetch(`${BASE_URL}/registry/?${qs.toString()}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * Fetch a single business by ID.
 * @param {number} id
 * @param {string} token
 */
export async function getBusinessByIdRequest(id, token) {
  try {
    const res = await fetch(`${BASE_URL}/registry/${id}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function updateBusinessRequest(businessId, payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/registry/${businessId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getBarangaysRequest(token) {
  const res = await fetch(`${BASE_URL}/registry/barangays`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return await handleResponse(res);
}

export async function getFlagsRequest(params = {}, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const qs = new URLSearchParams();
    if (params.page) qs.set("page", params.page);
    if (params.limit) qs.set("limit", params.limit);
    if (params.color) qs.set("color", params.color);
    if (params.barangayID) qs.set("barangayID", params.barangayID);

    const res = await fetch(`${BASE_URL}/flags/?${qs.toString()}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function createYellowFlagRequest(payload, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/yellow`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function escalateFlagToBlackRequest(logId, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/${logId}/black`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function runDetectionRequest(token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/run-detection`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function cancelRunDetection(token) {
  if (!token) throw new Error("Missing authentication token.");
  try {
    const res = await fetch(`${BASE_URL}/flags/cancel-detection`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getDetectionQuotaRequest(token) {
  if (!token) throw new Error("Missing authentication token.");
  try {
    const res = await fetch(`${BASE_URL}/flags/detection-quota`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function updateFlagLocationRequest(logId, lat, lng, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/${logId}/location`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ latitude: lat, longitude: lng }),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function deleteFlagRequest(logId, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/${logId}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function updateFlagColorRequest(logId, color, token) {
  if (!token) {
    throw new Error("Missing authentication token.");
  }

  try {
    const res = await fetch(`${BASE_URL}/flags/${logId}/color`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ color }),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

// ── User Management ───────────────────────────────────────────────────────────

export async function getUsersRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/users/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function createUserRequest(payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/users/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function updateUserRequest(userId, payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function deleteUserRequest(userId, token) {
  try {
    const res = await fetch(`${BASE_URL}/users/${userId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

// ── Inspections ───────────────────────────────────────────────────────────────

/**
 * GET /api/inspections/tasks
 * Inspector's own assigned/in-progress tasks.
 */
export async function getInspectorTasksRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/inspections/tasks`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * POST /api/inspections/assign
 * Admin assigns a flag to an inspector.
 * @param {{ logID: number, userID: number, deadline?: string }} payload
 */
export async function assignInspectionRequest(payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/inspections/assign`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * POST /api/inspections/:reportId/reassign
 * Admin sends a submitted report back for inspector redo (→ Reassigned).
 */
export async function reassignSubmittedInspectionRequest(
  reportId,
  userID,
  deadline,
  token,
) {
  try {
    const res = await fetch(`${BASE_URL}/inspections/${reportId}/reassign`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ userID, deadline }),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * POST /api/inspections/submit
 * Inspector submits their field report.
 * @param {{ logID, inspectionResult, verifiedLat?, verifiedLng?, notes?, photoURL? }} payload
 */
export async function submitInspectionRequest(payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/inspections/submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * POST /api/inspections/:id/verify
 * Admin verifies a submitted report → updates flagColor.
 * @param {number} reportId
 */
export async function verifyInspectionRequest(reportId, token) {
  try {
    const res = await fetch(`${BASE_URL}/inspections/${reportId}/verify`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * GET /api/inspections
 * Admin: all reports, filterable by status and barangayID.
 * @param {{ status?, barangayID?, page?, limit? }} params
 */
export async function getInspectionsRequest(params = {}, token) {
  try {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.barangayID) qs.set("barangayID", params.barangayID);
    if (params.page) qs.set("page", params.page);
    if (params.limit) qs.set("limit", params.limit);

    const res = await fetch(`${BASE_URL}/inspections/?${qs.toString()}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * GET /api/users (reuse if you already have this, otherwise add it)
 * Fetch inspector list for the assign dropdown.
 */
export async function getInspectorsRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/users/?role=Inspector`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export const verify2faRequest = async (tempToken, code) => {
  const response = await fetch(`${BASE_URL}/auth/verify-2fa-login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${tempToken}`,
    },
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(
      errorData.message || errorData.error || "Failed to verify 2FA code.",
    );
  }

  return await response.json();
};

// ── Analytics & WLC Config ────────────────────────────────────────────────────

export async function getWlcConfigRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/analytics/wlc-config`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function updateWlcConfigRequest(payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/analytics/wlc-config`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

/**
 * Normalize (token, filters?) vs (filters, token) — same ambiguity as getFlagsRequest(params, token).
 * JWT heuristic: long dotted string (typical access_token shape).
 */
function resolveTokenAndOptionalFilters(arg1, arg2) {
  const looksLikeJwt = (v) =>
    typeof v === "string" &&
    v.trim().length > 15 &&
    (v.match(/\./g) || []).length >= 2;

  const isFilterShape = (v) =>
    v != null && typeof v === "object" && !Array.isArray(v);

  if (looksLikeJwt(arg1)) {
    return {
      token: arg1.trim(),
      filters: isFilterShape(arg2) && !looksLikeJwt(arg2) ? arg2 : {},
    };
  }
  if (looksLikeJwt(arg2)) {
    return {
      token: arg2.trim(),
      filters: isFilterShape(arg1) && !looksLikeJwt(arg1) ? arg1 : {},
    };
  }
  const t = typeof arg1 === "string" ? arg1.trim() : "";
  return {
    token: t,
    filters: isFilterShape(arg2) ? arg2 : {},
  };
}

function authHeaders(accessToken) {
  const h = new Headers();
  h.set("Authorization", `Bearer ${accessToken}`);
  return h;
}

/** Build query string for GET /analytics/all filters (snake_case keys match backend). */
function analyticsFiltersToSearchParams(filters = {}) {
  const qs = new URLSearchParams();
  if (!filters || typeof filters !== "object") return qs;
  const set = (k, v) => {
    if (v === undefined || v === null || v === "") return;
    if (Array.isArray(v)) {
      if (v.length === 0) return;
      qs.set(k, v.join(","));
      return;
    }
    qs.set(k, String(v));
  };
  set("barangay_ids", filters.barangay_ids);
  set("barangay_id", filters.barangay_id);
  set("application_status", filters.application_status);
  set("line_of_business", filters.line_of_business);
  set("business_type", filters.business_type);
  set("business_size", filters.business_size);
  set("renewal_from", filters.renewal_from);
  set("renewal_to", filters.renewal_to);
  set("flag_color", filters.flag_color);
  set("detected_from", filters.detected_from);
  set("detected_to", filters.detected_to);
  set("inspection_result", filters.inspection_result);
  set("verification_status", filters.verification_status);
  set("inspection_from", filters.inspection_from);
  set("inspection_to", filters.inspection_to);
  return qs;
}

// For Dashboard overview cards and charts (flag counts, inspection stats, etc.)
// Accepts (token, filters) or (filters, token) like getFlagsRequest(params, token).
export async function getAnalyticsOverviewRequest(arg1, arg2) {
  try {
    const { token, filters } = resolveTokenAndOptionalFilters(arg1, arg2);
    if (!token) {
      throw new Error("Missing authentication token.");
    }
    const qs = analyticsFiltersToSearchParams(filters);
    const q = qs.toString();
    const url = q
      ? `${BASE_URL}/analytics/all?${q}`
      : `${BASE_URL}/analytics/all`;
    const res = await fetch(url, {
      method: "GET",
      headers: authHeaders(token),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getAnalyticsFilterMetadataRequest(token) {
  try {
    const { token: accessToken } = resolveTokenAndOptionalFilters(
      token,
      undefined,
    );
    if (!accessToken) {
      throw new Error("Missing authentication token.");
    }
    const res = await fetch(`${BASE_URL}/analytics/filter-metadata`, {
      method: "GET",
      headers: authHeaders(accessToken),
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function getOpsRankingsRequest(token) {
  try {
    const res = await fetch(`${BASE_URL}/analytics/ops-rankings`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}

export async function sendAnalyticsChatRequest(payload, token) {
  try {
    const res = await fetch(`${BASE_URL}/analytics/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify(payload)
    });
    return await handleResponse(res);
  } catch (err) {
    connectionGuard(err);
  }
}
