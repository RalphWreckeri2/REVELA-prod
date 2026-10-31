import assert from "node:assert/strict";
import test from "node:test";
import {
  getBarangayOverviewRequest,
  getRegistryStatusBySizeRequest,
} from "./api.js";

test("barangay overview sends the primary line-of-business key and returns its response", async () => {
  const originalFetch = globalThis.fetch;
  const expected = {
    overall: { registry_total: 8 },
    barangays: Array.from({ length: 16 }, (_, index) => ({
      barangayID: index + 1,
      registry_total: index === 0 ? 8 : 0,
    })),
  };
  let requestUrl;
  let requestOptions;

  globalThis.fetch = async (url, options) => {
    requestUrl = new URL(url);
    requestOptions = options;
    return {
      ok: true,
      json: async () => expected,
    };
  };

  try {
    const response = await getBarangayOverviewRequest("test-token", {
      line_of_business_key: "barbershopactivities",
    });

    test("registry status by size sends registry scope filters as a read-only request", async () => {
      const originalFetch = globalThis.fetch;
      const expected = {
        as_of: "2026-04-07T12:00:00+00:00",
        statuses: ["Active", "Expired", "Revoked", "Pending", "Closed"],
        municipality: { total: 4 },
        barangays: [],
      };
      let requestUrl;
      let requestOptions;

      globalThis.fetch = async (url, options) => {
        requestUrl = new URL(url);
        requestOptions = options;
        return {
          ok: true,
          json: async () => expected,
        };
      };

      try {
        const response = await getRegistryStatusBySizeRequest("test-token", {
          barangay_ids: [3, 4],
          business_size: "MICRO",
          application_status: "Active",
          line_of_business_key: "retailsellinggroceries",
        });
        assert.equal(
          requestUrl.pathname,
          "/api/analytics/registry-status-by-size",
        );
        assert.equal(requestUrl.searchParams.get("barangay_ids"), "3,4");
        assert.equal(requestUrl.searchParams.get("business_size"), "MICRO");
        assert.equal(requestUrl.searchParams.get("application_status"), "Active");
        assert.equal(
          requestUrl.searchParams.get("line_of_business_key"),
          "retailsellinggroceries",
        );
        assert.equal(requestOptions.method, "GET");
        assert.equal(requestOptions.cache, "no-store");
        assert.equal(response.municipality.total, 4);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
    assert.equal(
      requestUrl.searchParams.get("line_of_business_key"),
      "barbershopactivities",
    );
    assert.equal(response.overall.registry_total, 8);
    assert.equal(requestOptions.cache, "no-store");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
