/** Same identity review for office confirmation and inspection verification. */
export async function confirmBusinessID({ businessID, review, registryFields, preview, save, setReview, setError }) {
  const id = businessID.trim();
  if (!id) {
    setError("Official Business ID is required.");
    return null;
  }

  // Always obtain current server data, including on the final click after a preview.
  const current = await preview(id);
  if (review && (current.reviewToken !== review.reviewToken || current.businessID !== review.businessID)) {
    setReview(current);
    setError("The registry or pin changed. Check the updated record and confirm again.");
    return null;
  }
  if (current.registryExists && !review) {
    setReview(current);
    return null;
  }
  const missing = current.missingRequiredFields?.filter(field => !String(registryFields[field] || "").trim()) || [];
  if (missing.length) {
    setReview(current);
    setError("Provide the missing official name or barangay before confirming.");
    return null;
  }
  return save(current);
}
