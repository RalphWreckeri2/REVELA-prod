import { useEffect, useState } from "react";

export default function AuthenticatedEvidenceImage({
  url,
  token,
  alt,
  onClick,
  style,
}) {
  const requestKey = `${url}\u0000${token}`;
  const [imageState, setImageState] = useState({
    requestKey: "",
    imageUrl: "",
    failed: false,
  });

  useEffect(() => {
    if (!url || !token) return undefined;

    const controller = new AbortController();
    let objectUrl;
    let active = true;

    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Evidence request was rejected.");
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) {
          setImageState({ requestKey, imageUrl: objectUrl, failed: false });
        }
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") {
          setImageState({ requestKey, imageUrl: "", failed: true });
        }
      });

    return () => {
      active = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, token, requestKey]);

  if (!url || !token) {
    return (
      <div
        role="img"
        aria-label={`${alt}: unavailable`}
        style={{
          ...style,
          display: "grid",
          placeItems: "center",
          background: "var(--color-card-alt)",
          color: "var(--color-muted)",
          fontSize: 12,
        }}
      >
        Evidence unavailable
      </div>
    );
  }

  const isCurrentRequest = imageState.requestKey === requestKey;

  if (isCurrentRequest && imageState.failed) {
    return (
      <div
        role="img"
        aria-label={`${alt}: unavailable`}
        style={{
          ...style,
          display: "grid",
          placeItems: "center",
          background: "var(--color-card-alt)",
          color: "var(--color-muted)",
          fontSize: 12,
        }}
      >
        Evidence unavailable
      </div>
    );
  }

  if (!isCurrentRequest || !imageState.imageUrl) {
    return (
      <div
        role="status"
        aria-label={`Loading ${alt}`}
        style={{
          ...style,
          display: "grid",
          placeItems: "center",
          background: "var(--color-card-alt)",
          color: "var(--color-muted)",
          fontSize: 12,
        }}
      >
        Loading evidence…
      </div>
    );
  }

  return (
    <img
      src={imageState.imageUrl}
      alt={alt}
      onClick={onClick}
      style={{ ...style, cursor: onClick ? "zoom-in" : undefined }}
    />
  );
}
