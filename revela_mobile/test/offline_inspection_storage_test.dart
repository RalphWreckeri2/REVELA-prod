import 'dart:io';
import 'dart:convert';

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
    final storage = OfflineInspectionStorage(
      databasePath: '${tempDir.path}/inspection.db',
    );

    await storage.initialize();

    final draft = InspectionDraft(
      id: 1,
      logId: 42,
      reportId: 99,
      inspectionResult: 'Yellow',
      notes: 'Offline draft',
      noticeLevel: 1,
      verifiedLat: 14.6,
      verifiedLng: 121.1,
      verifiedAccuracy: 12.4,
      evidencePaths: const ['local/photo.jpg'],
      submittedAt: '2026-10-14T02:46:00.000Z',
      createdAt: DateTime.now().toUtc().toIso8601String(),
      updatedAt: DateTime.now().toUtc().toIso8601String(),
      status: DraftStatus.draft,
      ownerUserId: 'inspector-a',
    );

    final savedId = await storage.saveDraft(draft);
    final db = await storage.database();
    final count = firstIntValue(
      await db.rawQuery('SELECT COUNT(*) FROM inspection_drafts'),
    );
    final drafts = await storage.getDrafts(ownerUserId: 'inspector-a');

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
    expect(drafts.first.verifiedAccuracy, 12.4);
    expect(drafts.first.submittedAt, '2026-10-14T02:46:00.000Z');

    await storage.close();
    tempDir.deleteSync(recursive: true);
  });

  test(
    'accepted submission updates only its account and assignment cycle',
    () async {
      final tempDir = Directory.systemTemp.createTempSync(
        'revela_submitted_task_cache_test',
      );
      final storage = OfflineInspectionStorage(
        databasePath: '${tempDir.path}/inspection.db',
      );
      await storage.initialize();

      final db = await storage.database();
      Future<void> insertTask({
        required String userId,
        required int reportId,
        required int cycleId,
        required String status,
      }) async {
        final payload = {
          'reportID': reportId,
          'logID': 77,
          'assignmentCycleID': cycleId,
          'verificationStatus': status,
          'inspectionResult': null,
        };
        await db.insert('inspections', {
          'user_id': userId,
          'reportID': reportId,
          'logID': 77,
          'payload': jsonEncode(payload),
          'verificationStatus': status,
          'flagColor': 'Yellow',
        });
      }

      await insertTask(
        userId: 'inspector-a',
        reportId: 99,
        cycleId: 3,
        status: 'Assigned',
      );
      await insertTask(
        userId: 'inspector-a',
        reportId: 99,
        cycleId: 4,
        status: 'Assigned',
      );
      await insertTask(
        userId: 'inspector-b',
        reportId: 99,
        cycleId: 3,
        status: 'Assigned',
      );
      await storage.saveCachedTasks([
        {
          'reportID': 99,
          'assignmentCycleID': 3,
          'verificationStatus': 'Assigned',
        },
        {
          'reportID': 99,
          'assignmentCycleID': 4,
          'verificationStatus': 'Assigned',
        },
      ], userId: 'inspector-a');

      await storage.updateCachedTaskStatus(
        99,
        verificationStatus: 'Submitted',
        inspectionResult: 'Red',
        assignmentCycleID: 3,
        userId: 'inspector-a',
      );

      final inspectorARows = await db.query(
        'inspections',
        where: 'user_id = ?',
        whereArgs: ['inspector-a'],
        orderBy: 'id',
      );
      final inspectorBRows = await db.query(
        'inspections',
        where: 'user_id = ?',
        whereArgs: ['inspector-b'],
      );
      final cycle3Payload =
          jsonDecode(inspectorARows.first['payload']! as String)
              as Map<String, dynamic>;
      final cycle4Payload =
          jsonDecode(inspectorARows.last['payload']! as String)
              as Map<String, dynamic>;
      final bPayload =
          jsonDecode(inspectorBRows.single['payload']! as String)
              as Map<String, dynamic>;
      final taskSnapshot = await storage.getCachedTasks(userId: 'inspector-a');

      expect(cycle3Payload['verificationStatus'], 'Submitted');
      expect(cycle3Payload['inspectionResult'], 'Red');
      expect(cycle4Payload['verificationStatus'], 'Assigned');
      expect(bPayload['verificationStatus'], 'Assigned');
      expect(taskSnapshot.first['verificationStatus'], 'Submitted');
      expect(taskSnapshot.first['inspectionResult'], 'Red');
      expect(taskSnapshot.last['verificationStatus'], 'Assigned');

      await storage.close();
      tempDir.deleteSync(recursive: true);
    },
  );

  test('v4 draft database upgrades without losing rows', () async {
    final tempDir = Directory.systemTemp.createTempSync(
      'revela_offline_upgrade_test',
    );
    final dbPath = '${tempDir.path}\\inspection.db';
    final legacyDb = await databaseFactory.openDatabase(
      dbPath,
      options: OpenDatabaseOptions(
        version: 4,
        onCreate: (db, _) async {
          await db.execute('''
            CREATE TABLE inspection_drafts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              logId INTEGER NOT NULL,
              reportId INTEGER NOT NULL,
              inspectionResult TEXT NOT NULL,
              notes TEXT,
              noticeLevel INTEGER NOT NULL DEFAULT 0,
              verifiedLat REAL,
              verifiedLng REAL,
              verifiedAccuracy REAL,
              evidencePaths TEXT,
              photoUrlPayload TEXT,
              createdAt TEXT NOT NULL,
              updatedAt TEXT NOT NULL,
              status TEXT NOT NULL
            )
          ''');
          await db.insert('inspection_drafts', {
            'logId': 42,
            'reportId': 99,
            'inspectionResult': 'Yellow',
            'notes': 'Existing pending inspection',
            'noticeLevel': 1,
            'evidencePaths': '[]',
            'createdAt': '2026-10-12T10:00:00Z',
            'updatedAt': '2026-10-12T10:00:00Z',
            'status': DraftStatus.draft.name,
          });
        },
      ),
    );
    await legacyDb.close();

    final storage = OfflineInspectionStorage(databasePath: dbPath);
    final drafts = await storage.getDrafts(ownerUserId: 'inspector-a');
    expect(drafts, isEmpty);

    final upgradedDb = await storage.database();
    final quarantinedRows = await upgradedDb.query(
      'inspection_drafts',
      where: 'isQuarantined = 1',
    );
    final columns = await upgradedDb.rawQuery(
      'PRAGMA table_info(inspection_drafts)',
    );
    expect(quarantinedRows, hasLength(1));
    expect(quarantinedRows.single['ownerUserId'], isNull);
    expect(quarantinedRows.single['status'], DraftStatus.draft.name);
    expect(quarantinedRows.single['submittedAt'], isNull);
    expect(
      columns.map((column) => column['name']),
      contains('assignmentCycleID'),
    );
    expect(columns.map((column) => column['name']), contains('submittedAt'));

    await storage.close();
    final restartedStorage = OfflineInspectionStorage(databasePath: dbPath);
    final afterRestart = await restartedStorage.getDrafts(
      ownerUserId: 'inspector-a',
    );
    expect(afterRestart, isEmpty);
    final retainedLegacyRows = await (await restartedStorage.database()).query(
      'inspection_drafts',
      where: 'isQuarantined = 1',
    );
    expect(retainedLegacyRows, hasLength(1));
    expect(retainedLegacyRows.single['notes'], 'Existing pending inspection');
    await restartedStorage.close();
    tempDir.deleteSync(recursive: true);
  });

  test(
    'draft reads and mutations stay scoped to the owning inspector',
    () async {
      final tempDir = Directory.systemTemp.createTempSync(
        'revela_draft_owner_test',
      );
      final storage = OfflineInspectionStorage(
        databasePath: '${tempDir.path}\\inspection.db',
      );
      await storage.initialize();
      InspectionDraft draftFor(String ownerUserId) => InspectionDraft(
        logId: 7,
        reportId: 42,
        assignmentCycleID: 3,
        inspectionResult: 'Yellow',
        noticeLevel: 0,
        evidencePaths: const [],
        createdAt: '2026-10-12T10:00:00Z',
        updatedAt: '2026-10-12T10:00:00Z',
        status: DraftStatus.draft,
        ownerUserId: ownerUserId,
      );

      final inspectorAId = await storage.saveDraft(draftFor('inspector-a'));
      final inspectorBId = await storage.saveDraft(draftFor('inspector-b'));

      expect(
        (await storage.getDrafts(ownerUserId: 'inspector-a')).single.id,
        inspectorAId,
      );
      expect(
        (await storage.getDrafts(ownerUserId: 'inspector-b')).single.id,
        inspectorBId,
      );
      expect(
        await storage.getDraftForAssignment(42, 3, ownerUserId: 'inspector-b'),
        isNotNull,
      );
      expect(
        await storage.getDraftForAssignment(42, 3, ownerUserId: 'inspector-c'),
        isNull,
      );

      await storage.updateDraftStatus(
        inspectorAId,
        DraftStatus.failed,
        ownerUserId: 'inspector-b',
      );
      await storage.deleteDraft(inspectorAId, ownerUserId: 'inspector-b');
      expect(
        (await storage.getDrafts(ownerUserId: 'inspector-a')).single.status,
        DraftStatus.draft,
      );
      expect(await storage.getDrafts(ownerUserId: 'inspector-b'), hasLength(1));

      await storage.clearAll(ownerUserId: 'inspector-a');
      expect(await storage.getDrafts(ownerUserId: 'inspector-a'), isEmpty);
      expect(await storage.getDrafts(ownerUserId: 'inspector-b'), hasLength(1));

      await storage.close();
      tempDir.deleteSync(recursive: true);
    },
  );

  test('drafts without a verified owner cannot be stored', () async {
    final tempDir = Directory.systemTemp.createTempSync(
      'revela_unowned_draft_test',
    );
    final storage = OfflineInspectionStorage(
      databasePath: '${tempDir.path}\\inspection.db',
    );
    await storage.initialize();
    final draft = InspectionDraft(
      logId: 7,
      reportId: 42,
      inspectionResult: 'Yellow',
      noticeLevel: 0,
      evidencePaths: const [],
      createdAt: '2026-10-12T10:00:00Z',
      updatedAt: '2026-10-12T10:00:00Z',
      status: DraftStatus.draft,
    );

    await expectLater(storage.saveDraft(draft), throwsArgumentError);
    expect(await storage.getDrafts(ownerUserId: 'inspector-a'), isEmpty);

    await storage.close();
    tempDir.deleteSync(recursive: true);
  });
}
