import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/inspection_service.dart';
 
void main() {
  group('InspectionTask Model Tests', () {
    test('fromJson parses valid JSON data correctly', () {
      final json = {
        'reportID': 5,
        'logID': 20,
        'detectedName': 'Coconut Bud Rot',
        'barangayName': 'San Jose',
        'flagColor': 'Red',
        'verificationStatus': 'Assigned',
        'irTimestamp': '2026-07-02 12:00:00',
      };
 
      final task = InspectionTask.fromJson(json);
 
      expect(task.reportID, 5);
      expect(task.logID, 20);
      expect(task.detectedName, 'Coconut Bud Rot');
      expect(task.barangayName, 'San Jose');
      expect(task.flagColor, 'Red');
      expect(task.verificationStatus, 'Assigned');
    });
 
    test('fromJson handles missing optional fields and uses fallback defaults', () {
      final json = {
        'reportID': '15', // string representation of int
        'logID': 45,
        'irTimestamp': '2026-07-02 12:00:00',
      };
 
      final task = InspectionTask.fromJson(json);
 
      expect(task.reportID, 15); // successfully parsed using _asInt
      expect(task.detectedName, 'Unknown'); // fallback default
      expect(task.barangayName, 'Unknown Barangay'); // fallback default
      expect(task.flagColor, 'Green'); // fallback default
      expect(task.remarks, isNull);
    });
  });
}
