import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/offline_inspection_storage.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

int? firstIntValue(List<Map<String, Object?>> rows) {
  if (rows.isEmpty) return null;
  return rows.first.values.first as int?;
}

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  test('saves and loads offline drafts', () async {
    final tempDir = Directory.systemTemp.createTempSync('revela_offline_test');
    final storage = OfflineInspectionStorage(databasePath: '${tempDir.path}/inspection.db');

    await storage.initialize();
    await storage.clearAll();

    final draft = InspectionDraft(
      id: 1,
      logId: 42,
      reportId: 99,
      inspectionResult: 'Yellow',
      notes: 'Offline draft',
      noticeLevel: 1,
      verifiedLat: 14.6,
      verifiedLng: 121.1,
      evidencePaths: const ['local/photo.jpg'],
      createdAt: DateTime.now().toUtc().toIso8601String(),
      updatedAt: DateTime.now().toUtc().toIso8601String(),
      status: DraftStatus.draft,
    );

    final savedId = await storage.saveDraft(draft);
    final db = await storage.database();
    final count = firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM inspection_drafts'));
    final drafts = await storage.getDrafts();

    // v3 consolidation: drafts, cached tasks AND the task cache all live in
    // this single database file.
    final tables = await db.rawQuery(
      "SELECT name FROM sqlite_master WHERE type = 'table' "
      "AND name IN ('inspection_drafts', 'cached_tasks', 'inspections')",
    );

    expect(savedId, greaterThan(0));
    expect(count, 1);
    expect(tables, hasLength(3));

    expect(drafts, hasLength(1));
    expect(drafts.first.inspectionResult, 'Yellow');
    expect(drafts.first.notes, 'Offline draft');

    await storage.close();
    tempDir.deleteSync(recursive: true);
  });
}
