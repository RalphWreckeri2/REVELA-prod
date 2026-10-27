import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/inspection_benchmark.dart';

void main() {
  test('disabled unless explicitly built with REVELA_BENCHMARK=true', () {
    if (!InspectionBenchmark.enabled) {
      expect(InspectionBenchmark.start(evidenceFiles: 0, preuploadedUrls: 0), isNull);
    }
  });

  test('fixture accepted response produces one CSV row and duplicate is separate', () {
    if (!InspectionBenchmark.enabled) return;
    final captured = <String>[];
    final original = debugPrint;
    debugPrint = (String? message, {int? wrapWidth}) {
      if (message != null) captured.add(message);
    };
    try {
      final trial = InspectionBenchmark.start(evidenceFiles: 1, preuploadedUrls: 0)!;
      trial.gpsFix = true;
      trial.accepted('mock-request', 200, false);
      trial.finish('completed');
      trial.finish('failed');
      expect(captured, hasLength(1));
      expect(captured.single, contains('"mock-request","200"'));
      expect(captured.single, contains('"completed"'));

      final duplicate = InspectionBenchmark.start(evidenceFiles: 0, preuploadedUrls: 1)!;
      duplicate.accepted('retry-id', 200, true);
      duplicate.finish('completed');
      expect(captured.last, contains('"already_accepted"'));
    } finally {
      debugPrint = original;
    }
  });
}
