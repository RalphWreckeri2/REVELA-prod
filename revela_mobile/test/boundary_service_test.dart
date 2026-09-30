import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/boundary_service.dart';
import 'package:revela_mobile/service/flag_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('BoundaryService Unit & Location Matching Tests', () {
    test('canonicalBarangayKey normalizes aliases accurately', () {
      expect(BoundaryService.canonicalBarangayKey('District I (Pob.)'), 'barangay 1');
      expect(BoundaryService.canonicalBarangayKey('Barangay I'), 'barangay 1');
      expect(BoundaryService.canonicalBarangayKey('District II (Pob.)'), 'barangay 2');
      expect(BoundaryService.canonicalBarangayKey('Barangay II'), 'barangay 2');
      expect(BoundaryService.canonicalBarangayKey('Barangay II-A (Pob.)'), 'barangay 2a');
      expect(BoundaryService.canonicalBarangayKey('Barangay II-A'), 'barangay 2a');
      expect(BoundaryService.canonicalBarangayKey('District III (Pob.)'), 'barangay 3');
      expect(BoundaryService.canonicalBarangayKey('Barangay III'), 'barangay 3');
      expect(BoundaryService.canonicalBarangayKey('District IV (Pob.)'), 'barangay 4');
      expect(BoundaryService.canonicalBarangayKey('Barangay IV'), 'barangay 4');
      expect(BoundaryService.canonicalBarangayKey('Lumang Lipa'), 'lumanglipa');
      expect(BoundaryService.canonicalBarangayKey('Barangay Lumanglipa'), 'lumanglipa');
      expect(BoundaryService.canonicalBarangayKey('Barangay San Sebastian'), 'sansebastian');
    });

    test('findBarangayForPoint accurately resolves barangays without substring false positives', () async {
      final boundaryService = BoundaryService();
      await boundaryService.loadBoundaries();

      final mockBarangays = [
        Barangay(id: 1, name: 'Barangay I'),
        Barangay(id: 2, name: 'Barangay II'),
        Barangay(id: 3, name: 'Barangay II-A'),
        Barangay(id: 4, name: 'Barangay III'),
        Barangay(id: 5, name: 'Barangay IV'),
        Barangay(id: 6, name: 'Barangay Bayorbor'),
        Barangay(id: 7, name: 'Barangay Bubuyan'),
        Barangay(id: 8, name: 'Barangay Calingatan'),
        Barangay(id: 9, name: 'Barangay Loob'),
        Barangay(id: 10, name: 'Barangay Lumanglipa'),
        Barangay(id: 11, name: 'Barangay Kinalaglagan'),
        Barangay(id: 12, name: 'Barangay Manggahan'),
        Barangay(id: 13, name: 'Barangay Nangkaan'),
        Barangay(id: 14, name: 'Barangay San Sebastian'),
        Barangay(id: 15, name: 'Barangay Santol'),
        Barangay(id: 16, name: 'Barangay Upa'),
      ];

      // Test point in District II: 13.960630, 121.113447
      final matchedBrgyII = boundaryService.findBarangayForPoint(13.960630, 121.113447, mockBarangays);
      expect(matchedBrgyII?.name, 'Barangay II');

      // Test point in Barangay II-A: 13.952260, 121.115799
      final matchedBrgyIIA = boundaryService.findBarangayForPoint(13.952260, 121.115799, mockBarangays);
      expect(matchedBrgyIIA?.name, 'Barangay II-A');

      // Test point in District III: 13.961458, 121.109487
      final matchedBrgyIII = boundaryService.findBarangayForPoint(13.961458, 121.109487, mockBarangays);
      expect(matchedBrgyIII?.name, 'Barangay III');

      // Test point in District IV: 13.956173, 121.117793
      final matchedBrgyIV = boundaryService.findBarangayForPoint(13.956173, 121.117793, mockBarangays);
      expect(matchedBrgyIV?.name, 'Barangay IV');

      // Test point in Lumanglipa: 13.975411, 121.090623
      final matchedLumanglipa = boundaryService.findBarangayForPoint(13.975411, 121.090623, mockBarangays);
      expect(matchedLumanglipa?.name, 'Barangay Lumanglipa');
    });
  });
}
