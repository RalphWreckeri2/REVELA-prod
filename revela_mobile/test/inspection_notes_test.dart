import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/utils/inspection_notes.dart';

void main() {
  test('plain notes use all 255 stored characters', () {
    expect(storedInspectionNotesLength('a' * 255, 0), 255);
    expect(availableInspectionNoteCharacters(0), 255);
  });

  for (final level in [1, 2, 3, 4]) {
    test('notice $level includes prefix and separator in stored limit', () {
      final capacity = availableInspectionNoteCharacters(level);
      expect(storedInspectionNotesLength('a' * capacity, level), 255);
      expect(storedInspectionNotesLength('a' * (capacity + 1), level), 256);
      expect(
        buildStoredInspectionNotes('  ', level),
        inspectionNoticePrefix(level),
      );
    });
  }

  test('Unicode scalar count matches the backend character limit', () {
    expect(storedInspectionNotesLength('🌿' * 255, 0), 255);
  });
}
