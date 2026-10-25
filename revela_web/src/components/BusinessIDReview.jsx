import "../styles/BusinessIDReview.css";

/** Shared identity fields and optional preview for both Green workflows. */
export default function BusinessIDReview({ businessID, setBusinessID, review, setReview,
  busy, setError, initialLinked = false, registryFields, setRegistryFields }) {
  const pin = review?.pin;
  return (
    <section className="business-id-review" aria-label="Official registry link">
      <label className="business-id-review__label" htmlFor="green-business-id">Official Business ID</label>
      <input className="business-id-review__input" id="green-business-id" type="text"
        placeholder="Enter office-issued Business ID" autoComplete="off" spellCheck="false"
        value={businessID} maxLength={50} required readOnly={initialLinked} disabled={busy}
        onChange={event => {
          setBusinessID(event.target.value);
          setReview(null);
          setRegistryFields({});
          setError("");
        }} />
      {review && <div className="business-id-review__preview">
        <strong>{review.registryExists ? "Existing official registry record — confirm it matches this pin" : "New registry entry"}</strong>
        <p>Business ID: {review.businessID}<br />
          Name: {review.registry.businessName || "Required below"}<br />
          Barangay: {review.barangays?.find(b => b.barangayID === review.registry.barangayID)?.barangayName || review.registry.barangayID || "Required below"}<br />
          Address: {review.registry.businessAddress || "Not recorded"}</p>
        <p>Original pin #{pin.logID}: {pin.detectedName || "Name not recorded"}<br />
          Location: {Number(pin.latitude).toFixed(6)}, {Number(pin.longitude).toFixed(6)}<br />
          Source: {pin.source || "unknown"}</p>
        {(review.missingRequiredFields || []).map(field => (
          <label className="business-id-review__label" key={field} htmlFor={`business-id-${field}`}>
            {field === "businessName" ? "Official business name" : "Barangay"} (required)
            {field === "barangayID" ? (
              <select className="business-id-review__input" id={`business-id-${field}`}
                value={registryFields[field] || ""} disabled={busy}
                onChange={event => {
                  setRegistryFields({ ...registryFields, [field]: Number(event.target.value) });
                  setError("");
                }}>
                <option value="">Select barangay…</option>
                {review.barangays?.map(b => <option key={b.barangayID} value={b.barangayID}>{b.barangayName}</option>)}
              </select>
            ) : (
              <input className="business-id-review__input" id={`business-id-${field}`}
                type="text" maxLength={255} value={registryFields[field] || ""} disabled={busy}
                onChange={event => {
                  setRegistryFields({ ...registryFields, [field]: event.target.value });
                  setError("");
                }} />
            )}
          </label>
        ))}
      </div>}
      <p className="business-id-review__hint">Links the official registration to this pin and preserves its location and history.</p>
    </section>
  );
}
