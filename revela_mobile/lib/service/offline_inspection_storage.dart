import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

enum DraftStatus { draft, syncing, synced, failed }

enum YellowFlagDraftStatus { pendingSync, submitting, needsAttention }

class YellowFlagDraft {
  final String clientSubmissionId;
  final String ownerUserId;
  final String businessName;
  final String? businessAddress;
  final double lat;
  final double lng;
  final int? barangayId;
  final String barangayName;
  final String? notes;
  final String createdAt;
  final String updatedAt;
  final YellowFlagDraftStatus status;
  final String? lastError;

  const YellowFlagDraft({
    required this.clientSubmissionId,
    required this.ownerUserId,
    required this.businessName,
    this.businessAddress,
    required this.lat,
    required this.lng,
    required this.barangayId,
    required this.barangayName,
    required this.notes,
    required this.createdAt,
    required this.updatedAt,
    required this.status,
    this.lastError,
  });

  Map<String, Object?> toMap() => {
    'clientSubmissionId': clientSubmissionId,
    'ownerUserId': ownerUserId,
    'businessName': businessName,
    'businessAddress': businessAddress,
    'lat': lat,
    'lng': lng,
    'barangayId': barangayId,
    'barangayName': barangayName,
    'notes': notes,
    'createdAt': createdAt,
    'updatedAt': updatedAt,
    'status': status.name,
    'lastError': lastError,
  };

  factory YellowFlagDraft.fromMap(Map<String, Object?> map) => YellowFlagDraft(
    clientSubmissionId: map['clientSubmissionId'] as String,
    ownerUserId: map['ownerUserId'] as String,
    businessName: map['businessName'] as String,
    businessAddress: map['businessAddress'] as String?,
    lat: (map['lat'] as num).toDouble(),
    lng: (map['lng'] as num).toDouble(),
    barangayId: map['barangayId'] as int?,
    barangayName: map['barangayName'] as String,
    notes: map['notes'] as String?,
    createdAt: map['createdAt'] as String,
    updatedAt: map['updatedAt'] as String,
    status: YellowFlagDraftStatus.values.firstWhere(
      (status) => status.name == map['status'],
      orElse: () => YellowFlagDraftStatus.pendingSync,
    ),
    lastError: map['lastError'] as String?,
  );
}

class InspectionDraft {
  final int? id;
  final int logId;
  final int reportId;
  final int? assignmentCycleID;
  final String inspectionResult;
  final String? notes;
  final int noticeLevel;
  final double? verifiedLat;
  final double? verifiedLng;
  final double? verifiedAccuracy;
  final List<String> evidencePaths;
  final String? photoUrlPayload;
  final String? submittedAt;
  final String createdAt;
  final String updatedAt;
  final DraftStatus status;
  final String? ownerUserId;
  final bool isQuarantined;

  String get assignmentKey => assignmentStatusKey(reportId, assignmentCycleID);

  const InspectionDraft({
    this.id,
    required this.logId,
    required this.reportId,
    this.assignmentCycleID,
    required this.inspectionResult,
    this.notes,
    required this.noticeLevel,
    this.verifiedLat,
    this.verifiedLng,
    this.verifiedAccuracy,
    required this.evidencePaths,
    this.photoUrlPayload,
    this.submittedAt,
    required this.createdAt,
    required this.updatedAt,
    required this.status,
    this.ownerUserId,
    this.isQuarantined = false,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'logId': logId,
      'reportId': reportId,
      'assignmentCycleID': assignmentCycleID,
      'inspectionResult': inspectionResult,
      'notes': notes,
      'noticeLevel': noticeLevel,
      'verifiedLat': verifiedLat,
      'verifiedLng': verifiedLng,
      'verifiedAccuracy': verifiedAccuracy,
      'evidencePaths': jsonEncode(evidencePaths),
      'photoUrlPayload': photoUrlPayload,
      'submittedAt': submittedAt,
      'createdAt': createdAt,
      'updatedAt': updatedAt,
      'status': status.name,
      'ownerUserId': ownerUserId,
      'isQuarantined': isQuarantined ? 1 : 0,
    };
  }

  factory InspectionDraft.fromMap(Map<String, dynamic> map) {
    return InspectionDraft(
      id: map['id'] as int?,
      logId: map['logId'] as int,
      reportId: map['reportId'] as int,
      assignmentCycleID: map['assignmentCycleID'] as int?,
      inspectionResult: map['inspectionResult'] as String,
      notes: map['notes'] as String?,
      noticeLevel: map['noticeLevel'] as int,
      verifiedLat: map['verifiedLat'] != null
          ? (map['verifiedLat'] as num).toDouble()
          : null,
      verifiedLng: map['verifiedLng'] != null
          ? (map['verifiedLng'] as num).toDouble()
          : null,
      verifiedAccuracy: map['verifiedAccuracy'] != null
          ? (map['verifiedAccuracy'] as num).toDouble()
          : null,
      evidencePaths: _decodePaths(map['evidencePaths'] as String?),
      photoUrlPayload: map['photoUrlPayload'] as String?,
      submittedAt: map['submittedAt'] as String?,
      createdAt: map['createdAt'] as String,
      updatedAt: map['updatedAt'] as String,
      status: DraftStatus.values.firstWhere(
        (value) =>
            value.name == (map['status'] as String? ?? DraftStatus.draft.name),
        orElse: () => DraftStatus.draft,
      ),
      ownerUserId: map['ownerUserId'] as String?,
      isQuarantined: (map['isQuarantined'] as int? ?? 0) != 0,
    );
  }

  static List<String> _decodePaths(String? value) {
    if (value == null || value.isEmpty) return [];
    try {
      final decoded = jsonDecode(value);
      if (decoded is List) {
        return decoded.map((e) => e.toString()).toList();
      }
    } catch (_) {
      return [];
    }
    return [];
  }
}

String assignmentStatusKey(int reportId, int? assignmentCycleID) =>
    '$reportId:${assignmentCycleID ?? 'legacy'}';

class OfflineInspectionStorage {
  OfflineInspectionStorage._internal({String? databasePath})
    : _databasePathOverride = databasePath;

  static final OfflineInspectionStorage _instance =
      OfflineInspectionStorage._internal();

  factory OfflineInspectionStorage({String? databasePath}) {
    if (databasePath != null) {
      return OfflineInspectionStorage._internal(databasePath: databasePath);
    }
    return _instance;
  }

  final String? _databasePathOverride;
  Database? _db;

  Future<void> initialize() async {
    if (_db != null) return;

    if (kIsWeb) {
      return;
    }

    final dbPath = await _databasePath();
    final normalizedDbPath = dbPath.replaceAll('\\', '/');
    final dbDirectory = Directory(p.dirname(normalizedDbPath));
    if (!await dbDirectory.exists()) {
      await dbDirectory.create(recursive: true);
    }
    _db = await openDatabase(
      normalizedDbPath,
      version: 9,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE IF NOT EXISTS inspection_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logId INTEGER NOT NULL,
            reportId INTEGER NOT NULL,
            assignmentCycleID INTEGER,
            inspectionResult TEXT NOT NULL,
            notes TEXT,
            noticeLevel INTEGER NOT NULL DEFAULT 0,
            verifiedLat REAL,
            verifiedLng REAL,
            verifiedAccuracy REAL,
            evidencePaths TEXT,
            photoUrlPayload TEXT,
            submittedAt TEXT,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL,
            status TEXT NOT NULL,
            ownerUserId TEXT NOT NULL,
            isQuarantined INTEGER NOT NULL DEFAULT 0
          )
        ''');
        await db.execute('''
          CREATE TABLE IF NOT EXISTS cached_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            payload TEXT NOT NULL,
            updatedAt TEXT NOT NULL
          )
        ''');
        await db.execute('''
          CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            reportID INTEGER,
            logID INTEGER,
            payload TEXT,
            verificationStatus TEXT,
            flagColor TEXT,
            deadline TEXT
          )
        ''');
        await _createYellowFlagDrafts(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          try {
            await db.execute(
              'ALTER TABLE cached_tasks ADD COLUMN user_id TEXT',
            );
          } catch (_) {}
        }
        if (oldVersion < 3) {
          // v3 consolidates the former separate revela_local.db into this
          // database — existing installs gain the task-cache table in place.
          await db.execute('''
            CREATE TABLE IF NOT EXISTS inspections (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT,
              reportID INTEGER,
              logID INTEGER,
              payload TEXT,
              verificationStatus TEXT,
              flagColor TEXT,
              deadline TEXT
            )
          ''');
        }
        if (oldVersion < 4) {
          await db.execute(
            'ALTER TABLE inspection_drafts ADD COLUMN verifiedAccuracy REAL',
          );
        }
        if (oldVersion < 5) {
          await db.execute(
            'ALTER TABLE inspection_drafts ADD COLUMN assignmentCycleID INTEGER',
          );
        }
        if (oldVersion < 6) {
          await db.execute(
            'ALTER TABLE inspection_drafts ADD COLUMN ownerUserId TEXT',
          );
          await db.execute(
            'ALTER TABLE inspection_drafts ADD COLUMN '
            'isQuarantined INTEGER NOT NULL DEFAULT 1',
          );
        }
        if (oldVersion < 7) {
          await _createYellowFlagDrafts(db);
        }
        if (oldVersion < 8) {
          await db.execute(
            'ALTER TABLE inspection_drafts ADD COLUMN submittedAt TEXT',
          );
        }
        if (oldVersion >= 7 && oldVersion < 9) {
          await db.execute(
            'ALTER TABLE yellow_flag_drafts ADD COLUMN businessAddress TEXT',
          );
        }
      },
    );
    try {
      await _db!.execute('ALTER TABLE cached_tasks ADD COLUMN user_id TEXT');
    } catch (_) {}
  }

  Future<void> _createYellowFlagDrafts(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS yellow_flag_drafts (
        clientSubmissionId TEXT NOT NULL,
        ownerUserId TEXT NOT NULL,
        businessName TEXT NOT NULL,
        businessAddress TEXT,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        barangayId INTEGER,
        barangayName TEXT NOT NULL,
        notes TEXT,
        createdAt TEXT NOT NULL,
        updatedAt TEXT NOT NULL,
        status TEXT NOT NULL,
        lastError TEXT,
        PRIMARY KEY (ownerUserId, clientSubmissionId)
      )
    ''');
  }

  Future<Database> database() async {
    await initialize();
    return _db!;
  }

  Future<String> _databasePath() async {
    if (_databasePathOverride != null) return _databasePathOverride;
    final databasesPath = await getDatabasesPath();
    return p.join(databasesPath, 'revela_inspection_drafts.db');
  }

  Future<int> saveDraft(InspectionDraft draft) async {
    final ownerUserId = draft.ownerUserId;
    if (ownerUserId == null || ownerUserId.isEmpty || draft.isQuarantined) {
      throw ArgumentError.value(
        ownerUserId,
        'draft.ownerUserId',
        'A draft must belong to an authenticated inspector.',
      );
    }
    final db = await database();
    final data = draft.toMap()..remove('id');
    data['isQuarantined'] = 0;
    if (draft.id != null) {
      final updated = await db.update(
        'inspection_drafts',
        data,
        where: 'id = ? AND ownerUserId = ? AND isQuarantined = 0',
        whereArgs: [draft.id, ownerUserId],
      );
      if (updated > 0) {
        return draft.id!;
      }
      final existingId = await db.query(
        'inspection_drafts',
        columns: ['ownerUserId'],
        where: 'id = ?',
        whereArgs: [draft.id],
        limit: 1,
      );
      if (existingId.isNotEmpty &&
          existingId.single['ownerUserId'] != ownerUserId) {
        throw StateError('Cannot change ownership of an inspection draft.');
      }
    }
    return db.transaction((txn) async {
      final cycleWhere = draft.assignmentCycleID == null
          ? 'assignmentCycleID IS NULL'
          : 'assignmentCycleID = ?';
      final cycleArgs = draft.assignmentCycleID == null
          ? <Object?>[ownerUserId, draft.reportId]
          : <Object?>[ownerUserId, draft.reportId, draft.assignmentCycleID];
      final existing = await txn.query(
        'inspection_drafts',
        columns: ['id'],
        where:
            'ownerUserId = ? AND isQuarantined = 0 AND reportId = ? AND $cycleWhere',
        whereArgs: cycleArgs,
        orderBy: 'id ASC',
        limit: 1,
      );
      if (existing.isNotEmpty) {
        return existing.first['id'] as int;
      }
      return txn.insert('inspection_drafts', data);
    });
  }

  Future<List<InspectionDraft>> getDrafts({
    required String ownerUserId,
    DraftStatus? status,
  }) async {
    if (ownerUserId.isEmpty) return [];
    final db = await database();
    final rows = await db.query(
      'inspection_drafts',
      where: status == null
          ? 'ownerUserId = ? AND isQuarantined = 0'
          : 'ownerUserId = ? AND isQuarantined = 0 AND status = ?',
      whereArgs: status == null ? [ownerUserId] : [ownerUserId, status.name],
      orderBy: 'updatedAt DESC',
    );
    return rows.map(InspectionDraft.fromMap).toList();
  }

  Future<InspectionDraft?> getDraftForReport(
    int reportId, {
    required String ownerUserId,
  }) async {
    if (ownerUserId.isEmpty) return null;
    final db = await database();
    final rows = await db.query(
      'inspection_drafts',
      where: 'reportId = ? AND ownerUserId = ? AND isQuarantined = 0',
      whereArgs: [reportId, ownerUserId],
      orderBy: 'id ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : InspectionDraft.fromMap(rows.first);
  }

  Future<InspectionDraft?> getDraftForAssignment(
    int reportId,
    int? assignmentCycleID, {
    required String ownerUserId,
  }) async {
    if (ownerUserId.isEmpty) return null;
    final db = await database();
    final rows = await db.query(
      'inspection_drafts',
      where: assignmentCycleID == null
          ? 'reportId = ? AND assignmentCycleID IS NULL AND ownerUserId = ? AND isQuarantined = 0'
          : 'reportId = ? AND assignmentCycleID = ? AND ownerUserId = ? AND isQuarantined = 0',
      whereArgs: assignmentCycleID == null
          ? [reportId, ownerUserId]
          : [reportId, assignmentCycleID, ownerUserId],
      orderBy: 'id ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : InspectionDraft.fromMap(rows.first);
  }

  Future<void> recoverInterruptedSyncs({required String ownerUserId}) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.update(
      'inspection_drafts',
      {
        'status': DraftStatus.draft.name,
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      },
      where: 'status = ? AND ownerUserId = ? AND isQuarantined = 0',
      whereArgs: [DraftStatus.syncing.name, ownerUserId],
    );
  }

  Future<void> saveYellowFlagDraft(YellowFlagDraft draft) async {
    if (draft.ownerUserId.isEmpty ||
        draft.businessName.trim().isEmpty ||
        draft.barangayName.trim().isEmpty) {
      throw ArgumentError('A Yellow Flag draft requires an owner and details.');
    }
    final db = await database();
    final data = draft.toMap();
    await db.insert(
      'yellow_flag_drafts',
      data,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<YellowFlagDraft>> getYellowFlagDrafts({
    required String ownerUserId,
  }) async {
    if (ownerUserId.isEmpty) return [];
    final db = await database();
    final rows = await db.query(
      'yellow_flag_drafts',
      where: 'ownerUserId = ?',
      whereArgs: [ownerUserId],
      orderBy: 'createdAt ASC',
    );
    return rows.map(YellowFlagDraft.fromMap).toList();
  }

  Future<void> updateYellowFlagDraftStatus({
    required String ownerUserId,
    required String clientSubmissionId,
    required YellowFlagDraftStatus status,
    String? lastError,
  }) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.update(
      'yellow_flag_drafts',
      {
        'status': status.name,
        'lastError': lastError,
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      },
      where: 'ownerUserId = ? AND clientSubmissionId = ?',
      whereArgs: [ownerUserId, clientSubmissionId],
    );
  }

  Future<void> deleteYellowFlagDraft({
    required String ownerUserId,
    required String clientSubmissionId,
  }) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.delete(
      'yellow_flag_drafts',
      where: 'ownerUserId = ? AND clientSubmissionId = ?',
      whereArgs: [ownerUserId, clientSubmissionId],
    );
  }

  Future<void> recoverInterruptedYellowFlagSyncs({
    required String ownerUserId,
  }) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.update(
      'yellow_flag_drafts',
      {
        'status': YellowFlagDraftStatus.pendingSync.name,
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      },
      where: 'status = ? AND ownerUserId = ?',
      whereArgs: [YellowFlagDraftStatus.submitting.name, ownerUserId],
    );
  }

  Future<void> saveCachedTasks(
    List<Map<String, dynamic>> tasks, {
    String? userId,
  }) async {
    final db = await database();
    if (userId != null && userId.isNotEmpty) {
      await db.delete(
        'cached_tasks',
        where: 'user_id = ?',
        whereArgs: [userId],
      );
      await db.insert('cached_tasks', {
        'user_id': userId,
        'payload': jsonEncode(tasks),
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      });
    } else {
      await db.delete('cached_tasks');
      await db.insert('cached_tasks', {
        'payload': jsonEncode(tasks),
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      });
    }
  }

  Future<void> updateCachedTaskStatus(
    int reportId, {
    required String verificationStatus,
    required String inspectionResult,
    String? submittedAt,
    String? submissionReceivedAt,
    // Omitted timestamps retain cached values; confirmed NULL clears them.
    bool replaceSubmittedAt = false,
    bool replaceSubmissionReceivedAt = false,
    int? assignmentCycleID,
    String? userId,
  }) async {
    final db = await database();
    await db.transaction((txn) async {
      final clauses = <String>['reportID = ?'];
      final args = <Object?>[reportId];
      if (userId != null && userId.isNotEmpty) {
        clauses.add('user_id = ?');
        args.add(userId);
      }

      final rows = await txn.query(
        'inspections',
        where: clauses.join(' AND '),
        whereArgs: args,
      );
      for (final row in rows) {
        final payload = _withSubmittedStatus(
          row['payload'] as String?,
          reportId: reportId,
          assignmentCycleID: assignmentCycleID,
          verificationStatus: verificationStatus,
          inspectionResult: inspectionResult,
          submittedAt: submittedAt,
          submissionReceivedAt: submissionReceivedAt,
          replaceSubmittedAt: replaceSubmittedAt,
          replaceSubmissionReceivedAt: replaceSubmissionReceivedAt,
        );
        if (payload == null) continue;
        await txn.update(
          'inspections',
          {
            'payload': jsonEncode(payload),
            'verificationStatus': verificationStatus,
          },
          where: 'id = ?',
          whereArgs: [row['id']],
        );
      }

      final cachedRows = await txn.query(
        'cached_tasks',
        columns: ['id', 'payload'],
        where: userId == null || userId.isEmpty ? null : 'user_id = ?',
        whereArgs: userId == null || userId.isEmpty ? null : [userId],
      );
      for (final row in cachedRows) {
        final raw = row['payload'] as String?;
        if (raw == null) continue;
        try {
          final decoded = jsonDecode(raw);
          if (decoded is! List) continue;
          var changed = false;
          final tasks = decoded.map((task) {
            if (task is! Map ||
                task['reportID']?.toString() != reportId.toString() ||
                task['assignmentCycleID']?.toString() !=
                    assignmentCycleID?.toString()) {
              return task;
            }
            changed = true;
            final submissionTimestamps = <String, dynamic>{};
            if (submittedAt != null || replaceSubmittedAt) {
              submissionTimestamps['submittedAt'] = submittedAt;
            }
            if (submissionReceivedAt != null || replaceSubmissionReceivedAt) {
              submissionTimestamps['submissionReceivedAt'] =
                  submissionReceivedAt;
            }
            return {
              ...Map<String, dynamic>.from(task),
              'verificationStatus': verificationStatus,
              'inspectionResult': inspectionResult,
              ...submissionTimestamps,
            };
          }).toList();
          if (changed) {
            await txn.update(
              'cached_tasks',
              {'payload': jsonEncode(tasks)},
              where: 'id = ?',
              whereArgs: [row['id']],
            );
          }
        } on FormatException catch (error) {
          debugPrint(
            'OfflineInspectionStorage retained malformed task snapshot: $error',
          );
        }
      }
    });
  }

  Map<String, dynamic>? _withSubmittedStatus(
    String? rawPayload, {
    required int reportId,
    required int? assignmentCycleID,
    required String verificationStatus,
    required String inspectionResult,
    String? submittedAt,
    String? submissionReceivedAt,
    bool replaceSubmittedAt = false,
    bool replaceSubmissionReceivedAt = false,
  }) {
    if (rawPayload == null) return null;
    try {
      final decoded = jsonDecode(rawPayload);
      if (decoded is! Map) return null;
      if (decoded['reportID']?.toString() != reportId.toString() ||
          decoded['assignmentCycleID']?.toString() !=
              assignmentCycleID?.toString()) {
        return null;
      }
      final submissionTimestamps = <String, dynamic>{};
      if (submittedAt != null || replaceSubmittedAt) {
        submissionTimestamps['submittedAt'] = submittedAt;
      }
      if (submissionReceivedAt != null || replaceSubmissionReceivedAt) {
        submissionTimestamps['submissionReceivedAt'] = submissionReceivedAt;
      }
      return {
        ...Map<String, dynamic>.from(decoded),
        'verificationStatus': verificationStatus,
        'inspectionResult': inspectionResult,
        ...submissionTimestamps,
      };
    } on FormatException catch (error) {
      debugPrint(
        'OfflineInspectionStorage retained malformed cached task payload for report $reportId: $error',
      );
      return null;
    }
  }

  Future<List<Map<String, dynamic>>> getCachedTasks({String? userId}) async {
    final db = await database();
    List<Map<String, dynamic>> rows;
    if (userId != null && userId.isNotEmpty) {
      rows = await db.query(
        'cached_tasks',
        where: 'user_id = ?',
        whereArgs: [userId],
        orderBy: 'updatedAt DESC',
        limit: 1,
      );
    } else {
      rows = await db.query(
        'cached_tasks',
        orderBy: 'updatedAt DESC',
        limit: 1,
      );
    }
    if (rows.isEmpty) return [];
    final payload = rows.first['payload'] as String?;
    if (payload == null || payload.isEmpty) return [];

    final decoded = jsonDecode(payload);
    if (decoded is! List) return [];

    return decoded
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  Future<void> deleteDraft(int id, {required String ownerUserId}) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.delete(
      'inspection_drafts',
      where: 'id = ? AND ownerUserId = ? AND isQuarantined = 0',
      whereArgs: [id, ownerUserId],
    );
  }

  Future<void> updateDraftStatus(
    int id,
    DraftStatus status, {
    required String ownerUserId,
  }) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.update(
      'inspection_drafts',
      {
        'status': status.name,
        'updatedAt': DateTime.now().toUtc().toIso8601String(),
      },
      where: 'id = ? AND ownerUserId = ? AND isQuarantined = 0',
      whereArgs: [id, ownerUserId],
    );
  }

  Future<void> clearAll({required String ownerUserId}) async {
    if (ownerUserId.isEmpty) return;
    final db = await database();
    await db.delete(
      'inspection_drafts',
      where: 'ownerUserId = ? AND isQuarantined = 0',
      whereArgs: [ownerUserId],
    );
    await db.delete(
      'cached_tasks',
      where: 'user_id = ?',
      whereArgs: [ownerUserId],
    );
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
  }
}
