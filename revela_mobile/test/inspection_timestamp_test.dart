import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/utils/date_utils.dart';

void main() {
  test(
    'converts UTC submission instants to Asia/Manila, including date rollover',
    () {
      expect(
        AppDateUtils.formatTimestampInManila('2025-10-13T18:46:00Z'),
        'Oct 14 · 2:46 AM',
      );
      expect(
        AppDateUtils.formatTimestampInManila('2025-10-14T02:46:00Z'),
        'Oct 14 · 10:46 AM',
      );
    },
  );

  test('honors explicit offsets and does not fabricate missing timestamps', () {
    expect(
      AppDateUtils.formatTimestampInManila('2025-10-13T19:00:00-05:00'),
      'Oct 14 · 8:00 AM',
    );
    expect(AppDateUtils.formatTimestampInManila(null), 'Timestamp unavailable');
  });
}
