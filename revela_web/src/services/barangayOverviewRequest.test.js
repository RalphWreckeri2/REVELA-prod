import assert from "node:assert/strict";
import test from "node:test";
import { getBarangayOverviewRequest } from "./api.js";

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
