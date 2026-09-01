import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

enum DraftStatus { draft, syncing, synced, failed }

class InspectionDraft {
  final int? id;
  final int logId;
  final int reportId;
  final String inspectionResult;
  final String? notes;
  final int noticeLevel;
  final double? verifiedLat;
  final double? verifiedLng;
  final List<String> evidencePaths;
  final String? photoUrlPayload;
  final String createdAt;
  final String updatedAt;
  final DraftStatus status;

  const InspectionDraft({
    this.id,
    required this.logId,
    required this.reportId,
    required this.inspectionResult,
    this.notes,
    required this.noticeLevel,
    this.verifiedLat,
    this.verifiedLng,
    required this.evidencePaths,
    this.photoUrlPayload,
    required this.createdAt,
    required this.updatedAt,
    required this.status,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'logId': logId,
      'reportId': reportId,
      'inspectionResult': inspectionResult,
      'notes': notes,
      'noticeLevel': noticeLevel,
      'verifiedLat': verifiedLat,
      'verifiedLng': verifiedLng,
      'evidencePaths': jsonEncode(evidencePaths),
      'photoUrlPayload': photoUrlPayload,
      'createdAt': createdAt,
      'updatedAt': updatedAt,
      'status': status.name,
    };
  }

  factory InspectionDraft.fromMap(Map<String, dynamic> map) {
    return InspectionDraft(
      id: map['id'] as int?,
      logId: map['logId'] as int,
      reportId: map['reportId'] as int,
      inspectionResult: map['inspectionResult'] as String,
      notes: map['notes'] as String?,
      noticeLevel: map['noticeLevel'] as int,
      verifiedLat: map['verifiedLat'] != null ? (map['verifiedLat'] as num).toDouble() : null,
      verifiedLng: map['verifiedLng'] != null ? (map['verifiedLng'] as num).toDouble() : null,
      evidencePaths: _decodePaths(map['evidencePaths'] as String?),
      photoUrlPayload: map['photoUrlPayload'] as String?,
      createdAt: map['createdAt'] as String,
      updatedAt: map['updatedAt'] as String,
      status: DraftStatus.values.firstWhere(
        (value) => value.name == (map['status'] as String? ?? DraftStatus.draft.name),
        orElse: () => DraftStatus.draft,
      ),
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

class OfflineInspectionStorage {
  OfflineInspectionStorage._internal({String? databasePath}) : _databasePathOverride = databasePath;

  static final OfflineInspectionStorage _instance = OfflineInspectionStorage._internal();

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
      version: 3,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE IF NOT EXISTS inspection_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logId INTEGER NOT NULL,
            reportId INTEGER NOT NULL,
            inspectionResult TEXT NOT NULL,
            notes TEXT,
            noticeLevel INTEGER NOT NULL DEFAULT 0,
            verifiedLat REAL,
            verifiedLng REAL,
            evidencePaths TEXT,
            photoUrlPayload TEXT,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL,
            status TEXT NOT NULL
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
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          try {
            await db.execute('ALTER TABLE cached_tasks ADD COLUMN user_id TEXT');
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
      },
    );
    try {
      await _db!.execute('ALTER TABLE cached_tasks ADD COLUMN user_id TEXT');
    } catch (_) {}
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
    final db = await database();
    final data = draft.toMap()..remove('id');
    if (draft.id != null) {
      final updated = await db.update(
        'inspection_drafts',
        data,
        where: 'id = ?',
        whereArgs: [draft.id],
      );
      if (updated > 0) {
        return draft.id!;
      }
    }
    return db.insert('inspection_drafts', data);
  }

  Future<List<InspectionDraft>> getDrafts({DraftStatus? status}) async {
    final db = await database();
    final rows = await db.query(
      'inspection_drafts',
      where: status == null ? null : 'status = ?',
      whereArgs: status == null ? null : [status.name],
      orderBy: 'updatedAt DESC',
    );
    return rows.map(InspectionDraft.fromMap).toList();
  }

  Future<void> saveCachedTasks(List<Map<String, dynamic>> tasks, {String? userId}) async {
    final db = await database();
    if (userId != null && userId.isNotEmpty) {
      await db.delete('cached_tasks', where: 'user_id = ?', whereArgs: [userId]);
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
      rows = await db.query('cached_tasks', orderBy: 'updatedAt DESC', limit: 1);
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

  Future<void> deleteDraft(int id) async {
    final db = await database();
    await db.delete('inspection_drafts', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> updateDraftStatus(int id, DraftStatus status) async {
    final db = await database();
    await db.update(
      'inspection_drafts',
      {'status': status.name, 'updatedAt': DateTime.now().toUtc().toIso8601String()},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> clearAll() async {
    final db = await database();
    await db.delete('inspection_drafts');
    await db.delete('cached_tasks');
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
  }
}
