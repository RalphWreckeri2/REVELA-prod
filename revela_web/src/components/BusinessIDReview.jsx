/** One explicit registry-identity review for Green field and office workflows. */
export default function BusinessIDReview({ businessID, setBusinessID, review, setReview,
  confirmed, setConfirmed, reviewing, setReviewing, busy, preview, setError,
  attestation, initialLinked = false, registryFields, setRegistryFields }) {
  const reviewID = async () => {
    setReviewing(true);
    setError("");
    setReview(null);
    setConfirmed(false);
    setRegistryFields({});
    try {
      setReview(await preview(businessID.trim()));
    } catch (error) {
      setError(error.message || "Could not review the Business ID.");
    } finally {
      setReviewing(false);
    }
  };
  const pin = review?.pin;
  return (
    <section aria-label="Official registry link" style={{ fontSize: 13, lineHeight: 1.6 }}>
      <label htmlFor="green-business-id">Official Business ID (required)</label>
      <input id="green-business-id" value={businessID} maxLength={50} required
        readOnly={initialLinked} disabled={busy || reviewing}
        style={{ display: "block", width: "100%", boxSizing: "border-box", margin: "8px 0" }}
        onChange={event => {
          setBusinessID(event.target.value);
          setReview(null);
          setConfirmed(false);
          setRegistryFields({});
        }} />
      <button type="button" className="ghost-btn" onClick={reviewID}
        disabled={!businessID.trim() || busy || reviewing}>
        {reviewing ? "Reviewing…" : "Review Business ID"}
      </button>
      {review && <div style={{ marginTop: 12 }}>
        <strong>{review.registryExists ? "Existing official registry record" : "New official registry record"}</strong>
        <p>Business ID: {review.businessID}<br />
          Name: {review.registry.businessName || "Required below"}<br />
          Barangay: {review.barangays?.find(b => b.barangayID === review.registry.barangayID)?.barangayName || review.registry.barangayID || "Required below"}<br />
          Address: {review.registry.businessAddress || "Not recorded"}</p>
        <p>Original pin #{pin.logID}: {pin.detectedName || "Name not recorded"}<br />
          Location: {Number(pin.latitude).toFixed(6)}, {Number(pin.longitude).toFixed(6)}<br />
          Source: {pin.source || "unknown"}</p>
        {!review.registryExists && <p>Only the ID, known name, barangay, and original pin location will be saved. Other official details remain unset until imported.</p>}
        {(review.missingRequiredFields || []).map(field => (
          <label key={field} style={{ display: "block", margin: "10px 0" }}>
            {field === "businessName" ? "Official business name" : "Barangay"} (required)
            {field === "barangayID" ? (
              <select value={registryFields[field] || ""} disabled={busy}
                onChange={event => {
                  setRegistryFields({ ...registryFields, [field]: Number(event.target.value) });
                  setConfirmed(false);
                }}>
                <option value="">Select barangay…</option>
                {review.barangays?.map(b => <option key={b.barangayID} value={b.barangayID}>{b.barangayName}</option>)}
              </select>
            ) : (
              <input value={registryFields[field] || ""} maxLength={255} disabled={busy}
                onChange={event => {
                  setRegistryFields({ ...registryFields, [field]: event.target.value });
                  setConfirmed(false);
                }} />
            )}
          </label>
        ))}
        <label style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
          <input type="checkbox" checked={confirmed} disabled={busy}
            onChange={event => setConfirmed(event.target.checked)} />
          {attestation}
        </label>
      </div>}
      <p>The official record and original pin will be linked together. The pin, coordinates, source, and history stay intact.</p>
    </section>
  );
}
