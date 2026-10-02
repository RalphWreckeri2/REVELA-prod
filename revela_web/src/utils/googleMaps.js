import { useLoadScript } from "@react-google-maps/api";

// Keep the Maps script URL identical across routes so navigation does not
// attempt to reload the API with a different set of libraries.
const MAP_LIBRARIES = ["marker"];

export function useGoogleMapsScript() {
  return useLoadScript({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "",
    libraries: MAP_LIBRARIES,
    version: "beta",
  });
}
