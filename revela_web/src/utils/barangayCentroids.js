export const DEFAULT_MAP_CENTER = { lat: 13.9667, lng: 121.1167 };

export const BARANGAY_CENTROIDS = {
  "barangay ii-a": { lat: 13.95226, lng: 121.115799 },
  "barangay ii-a (pob.)": { lat: 13.95226, lng: 121.115799 },
  bayorbor: { lat: 13.979234, lng: 121.095818 },
  bubuyan: { lat: 13.983266, lng: 121.108556 },
  calingatan: { lat: 13.962879, lng: 121.121234 },
  "district i": { lat: 13.955117, lng: 121.110199 },
  "district i (pob.)": { lat: 13.955117, lng: 121.110199 },
  "barangay i": { lat: 13.955117, lng: 121.110199 },
  "district ii": { lat: 13.96063, lng: 121.113447 },
  "district ii (pob.)": { lat: 13.96063, lng: 121.113447 },
  "barangay ii": { lat: 13.96063, lng: 121.113447 },
  "district iii": { lat: 13.961458, lng: 121.109487 },
  "district iii (pob.)": { lat: 13.961458, lng: 121.109487 },
  "barangay iii": { lat: 13.961458, lng: 121.109487 },
  "district iv": { lat: 13.956173, lng: 121.117793 },
  "district iv (pob.)": { lat: 13.956173, lng: 121.117793 },
  "barangay iv": { lat: 13.956173, lng: 121.117793 },
  kinalaglagan: { lat: 14.005574, lng: 121.094954 },
  loob: { lat: 13.980785, lng: 121.114404 },
  "lumang lipa": { lat: 13.974504, lng: 121.087937 },
  manggahan: { lat: 13.967686, lng: 121.08886 },
  nangkaan: { lat: 13.990223, lng: 121.089892 },
  "san sebastian": { lat: 13.984496, lng: 121.103597 },
  "san seb.": { lat: 13.984496, lng: 121.103597 },
  santol: { lat: 13.972238, lng: 121.10485 },
  upa: { lat: 13.968345, lng: 121.111783 },
};

export function getBarangayCentroid(barangayName) {
  if (!barangayName) return DEFAULT_MAP_CENTER;
  const raw = String(barangayName)
    .toLowerCase()
    .replace("barangay ", "")
    .replace("brgy. ", "")
    .trim();
  if (BARANGAY_CENTROIDS[raw]) return BARANGAY_CENTROIDS[raw];
  for (const key in BARANGAY_CENTROIDS) {
    if (raw.includes(key) || key.includes(raw)) {
      return BARANGAY_CENTROIDS[key];
    }
  }
  return DEFAULT_MAP_CENTER;
}
