export const ADM4_EN_TO_BARANGAY_ID = Object.freeze({
  "District I (Pob.)": 1,
  "District II (Pob.)": 2,
  "Barangay II-A (Pob.)": 3,
  "District III (Pob.)": 4,
  "District IV (Pob.)": 5,
  Bayorbor: 6,
  Bubuyan: 7,
  Calingatan: 8,
  Kinalaglagan: 9,
  "Lumang Lipa": 10,
  Loob: 11,
  Manggahan: 12,
  Nangkaan: 13,
  "San Sebastian": 14,
  Santol: 15,
  Upa: 16,
});

export function getBarangayIdForGeoJsonName(name) {
  return ADM4_EN_TO_BARANGAY_ID[name] ?? null;
}
