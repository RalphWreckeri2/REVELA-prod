import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmBusinessID } from "./businessIDReviewFlow.js";

for (const flow of ["office compliance", "inspection verification"]) {
  test(`${flow}: new office-issued ID can save on first final action`, async () => {
    const events = [];
    const result = await confirmBusinessID({ businessID: " 0007-A ", review: null, registryFields: {},
      preview: async id => { events.push(["preview", id]); return { businessID: "0007-A", registryExists: false, reviewToken: "current", missingRequiredFields: [] }; },
      save: async current => { events.push(["save", current.reviewToken]); return "saved"; },
      setReview: () => assert.fail("no extra confirmation for a new ID with complete pin details"),
      setError: assert.fail,
    });
    assert.equal(result, "saved");
    assert.deepEqual(events, [["preview", "0007-A"], ["save", "current"]]);
  });

  test(`${flow}: existing ID requires record preview and fresh lookup on confirmation`, async () => {
    let review = null;
    let lookups = 0;
    let saves = 0;
    const options = { businessID: "REG-01", registryFields: {},
      preview: async () => { lookups += 1; return { businessID: "REG-01", registryExists: true, reviewToken: "same" }; },
      save: async () => { saves += 1; },
      setReview: value => { review = value; }, setError: assert.fail };
    await confirmBusinessID({ ...options, review });
    assert.equal(saves, 0);
    assert.ok(review?.registryExists);
    await confirmBusinessID({ ...options, review });
    assert.equal(lookups, 2);
    assert.equal(saves, 1);
  });

  test(`${flow}: missing pin details pause; stale identity cannot save`, async () => {
    let review = null;
    let error = "";
    let token = "old";
    let saves = 0;
    const options = { businessID: "NEW-01", registryFields: {},
      preview: async () => ({ businessID: "NEW-01", registryExists: false, reviewToken: token, missingRequiredFields: ["businessName"] }),
      save: async () => { saves += 1; },
      setReview: value => { review = value; }, setError: value => { error = value; } };
    await confirmBusinessID({ ...options, review });
    assert.equal(saves, 0);
    assert.match(error, /missing official name or barangay/);
    token = "changed";
    await confirmBusinessID({ ...options, review, registryFields: { businessName: "Office name" } });
    assert.equal(saves, 0);
    assert.match(error, /changed/);
    await confirmBusinessID({ ...options, review, registryFields: { businessName: "Office name" } });
    assert.equal(saves, 1);
  });
}
