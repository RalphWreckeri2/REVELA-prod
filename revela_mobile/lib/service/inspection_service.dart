import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

import 'api_config.dart';
import 'auth_service.dart';
import 'offline_inspection_storage.dart';

class InspectionTask {
  final int reportID;
  final int logID;
  final String detectedName;
  final String barangayName;
  final String flagColor;
  final String verificationStatus;
  final String? remarks;
  final String? photoPath;
  final String? nearestLandmark;
  final double? latitude;
  final double? longitude;
  final String irTimestamp;

  /// Field result after inspector submits (null while still open).
  final String? inspectionResult;
  final String? deadline;
  final int currentNoticeLevel;

  InspectionTask({
    required this.reportID,
    required this.logID,
    required this.detectedName,
    required this.barangayName,
    required this.flagColor,
    required this.verificationStatus,
    this.remarks,
    this.photoPath,
    this.nearestLandmark,
    this.latitude,
    this.longitude,
    required this.irTimestamp,
    this.inspectionResult,
    this.deadline,
    this.currentNoticeLevel = 0,
  });

  factory InspectionTask.fromJson(Map<String, dynamic> json) {
    return InspectionTask(
      reportID: _asInt(json['reportID']),
      logID: _asInt(json['logID']),
      detectedName: json['detectedName']?.toString() ?? 'Unknown',
      barangayName: json['barangayName']?.toString() ?? 'Unknown Barangay',
      flagColor: json['flagColor']?.toString() ?? 'Green',
      verificationStatus: json['verificationStatus']?.toString() ?? 'Assigned',
      remarks: json['remarks']?.toString(),
      photoPath: json['photoPath']?.toString(),
      nearestLandmark: json['nearestLandmark']?.toString(),
      latitude: json['latitude'] != null
          ? double.tryParse(json['latitude'].toString())
          : null,
      longitude: json['longitude'] != null
          ? double.tryParse(json['longitude'].toString())
          : null,
      irTimestamp: json['irTimestamp']?.toString() ?? '',
      inspectionResult: json['inspectionResult']?.toString(),
      deadline: json['deadline']?.toString(),
      currentNoticeLevel: _asInt(json['currentNoticeLevel']),
    );
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    return int.tryParse(v?.toString() ?? '') ?? 0;
  }

  /// Safely parse legacy single strings or new JSON arrays of photo paths.
  List<String> get photoPaths {
    if (photoPath == null || photoPath!.isEmpty) return [];
    try {
      final decoded = jsonDecode(photoPath!);
      if (decoded is List) {
        return decoded.map((e) => e.toString()).toList();
      }
    } catch (_) {
      // Not a JSON array, treat as legacy single string
      return [photoPath!];
    }
    return [photoPath!];
  }

  Map<String, dynamic> toJson() {
    return {
      'reportID': reportID,
      'logID': logID,
      'detectedName': detectedName,
      'barangayName': barangayName,
      'flagColor': flagColor,
      'verificationStatus': verificationStatus,
      'remarks': remarks,
      'photoPath': photoPath,
      'nearestLandmark': nearestLandmark,
      'latitude': latitude,
      'longitude': longitude,
      'irTimestamp': irTimestamp,
      'inspectionResult': inspectionResult,
      'deadline': deadline,
      'currentNoticeLevel': currentNoticeLevel,
    };
  }
}

class InspectionService {
  static final InspectionService _instance = InspectionService._internal();
  factory InspectionService() => _instance;

  final AuthService _auth = AuthService();
  final OfflineInspectionStorage _offlineStorage = OfflineInspectionStorage();
  final ValueNotifier<Map<int, DraftStatus>> pendingDraftStatuses =
      ValueNotifier<Map<int, DraftStatus>>({});
  final ValueNotifier<SyncNotification?> syncNotification =
      ValueNotifier<SyncNotification?>(null);
  Timer? _reconnectTimer;
  bool _wasReachable = false;
  bool _isSyncing = false;

  InspectionService._internal() {
    _startReconnectMonitor();
  }

  void _startReconnectMonitor() {
    _reconnectTimer ??= Timer.periodic(const Duration(seconds: 10), (_) {
      unawaited(_checkReconnect());
    });
    unawaited(_checkReconnect());
  }

  Future<void> _checkReconnect() async {
    // Don't attempt sync while logged out (e.g. after a force-stop on
    // connection loss) — the POST would 401 and the retry classifier would
    // needlessly cycle the drafts. Resetting _wasReachable here guarantees
    // the offline→online transition fires once the user logs back in.
    if (!_auth.isAuthenticated) {
      _wasReachable = false;
      return;
    }
    final reachable = await ApiConfig.ensureReachable() != null;
    final restored = reachable && !_wasReachable;
    _wasReachable = reachable;
    if (restored && await getPendingDraftCount() > 0) {
      syncNotification.value = const SyncNotification.started();
      final synced = await syncPendingReports();
      if (synced > 0) {
        syncNotification.value = SyncNotification.completed(synced);
      }
    }
  }

  Future<void> refreshPendingDraftStatuses() async {
    final drafts = await _offlineStorage.getDrafts();
    pendingDraftStatuses.value = {
      for (final draft in drafts) draft.logId: draft.status,
    };
  }

  /// Active assignments from the server (Assigned + Reassigned).
  /// The task cache lives in the single consolidated offline database owned
  /// by [OfflineInspectionStorage] (table `inspections`), so queued drafts
  /// and cached tasks share one SQLite file.
  Future<List<InspectionTask>> _queryLocalTasks(
    String userId, {
    bool activeOnly = true,
  }) async {
    final db = await _offlineStorage.database();
    final where =
        'user_id = ?${activeOnly ? " AND (verificationStatus IN ('Assigned','Reassigned'))" : ''}';
    List<Map<String, Object?>> rows = await db.query(
      'inspections',
      where: where,
      whereArgs: [userId],
    );
    // If no rows were found and the userId looks numeric, try integer form too
    if (rows.isEmpty) {
      try {
        final asInt = int.tryParse(userId);
        if (asInt != null) {
          rows = await db.query(
            'inspections',
            where: where,
            whereArgs: [asInt],
          );
        }
      } catch (_) {}
    }
    final List<InspectionTask> results = [];
    for (final r in rows) {
      final raw = r['payload'] as String? ?? '{}';
      try {
        final Map<String, dynamic> map = jsonDecode(raw);
        results.add(InspectionTask.fromJson(map));
      } catch (_) {
        // If payload isn't JSON, attempt to construct minimal map
        final m = <String, dynamic>{
          'reportID': r['reportID'],
          'logID': r['logID'],
          'verificationStatus': r['verificationStatus'],
          'flagColor': r['flagColor'],
          'deadline': r['deadline'],
          'detectedName': 'Offline Item',
          'barangayName': 'Unknown',
        };
        results.add(InspectionTask.fromJson(m));
      }
    }
    return results;
  }

  Future<void> _saveLocalTasks(
    String userId,
    List<InspectionTask> tasks,
  ) async {
    if (userId.isEmpty) return;
    final db = await _offlineStorage.database();
    await db.transaction((txn) async {
      for (final task in tasks) {
        try {
          await txn.delete(
            'inspections',
            where: 'user_id = ? AND reportID = ? AND logID = ?',
            whereArgs: [userId, task.reportID, task.logID],
          );
          await txn.insert('inspections', {
            'user_id': userId,
            'reportID': task.reportID,
            'logID': task.logID,
            'payload': jsonEncode(task.toJson()),
            'verificationStatus': task.verificationStatus,
            'flagColor': task.flagColor,
            'deadline': task.deadline,
          });
        } catch (e) {
          debugPrint('Failed to save local task for user $userId: $e');
        }
      }
    });
  }

  Future<List<InspectionTask>> getMyTasks() async {
    try {
      final response = await _auth.dio.get('/api/inspections/tasks');
      final List<dynamic> data = response.data['data'] ?? [];
      final tasks = data
          .map((e) => InspectionTask.fromJson(e as Map<String, dynamic>))
          .toList();
      final userId = await _auth.getAuthenticatedUserId();
      if (userId != null && userId.isNotEmpty) {
        await _saveLocalTasks(userId, tasks);
      }
      return tasks;
    } on DioException catch (e) {
      debugPrint(
        'InspectionService.getMyTasks (network failed): ${e.response?.data ?? e.message}',
      );
      // Fallback to local DB filtered by authenticated_user_id
      try {
        final userId = await _auth.getAuthenticatedUserId();
        if (userId == null) return [];
        return await _queryLocalTasks(userId, activeOnly: true);
      } catch (ex) {
        debugPrint('InspectionService.local fallback failed: $ex');
        return [];
      }
    }
  }

  /// Public helper to read locally cached tasks for a given user id without
  /// attempting any network call. Useful to hydrate UI immediately while a
  /// background reachability probe or sync is performed.
  Future<List<InspectionTask>> getLocalTasksForUser(
    String? userId, {
    bool activeOnly = true,
  }) async {
    try {
      var uid = userId;
      if (uid == null || uid.isEmpty) {
        // Attempt to fall back to authenticated_user_id from secure storage
        final auth = AuthService();
        uid = await auth.getAuthenticatedUserId();
        if (uid == null || uid.isEmpty) {
          debugPrint(
            'getLocalTasksForUser: no userId provided and no authenticated_user_id found',
          );
          return [];
        }
      }
      // Ensure we pass a string representation to the SQL query
      return await _queryLocalTasks(uid.toString(), activeOnly: activeOnly);
    } catch (e) {
      debugPrint('getLocalTasksForUser failed: $e');
      return [];
    }
  }

  /// Full history for the logged-in inspector (all statuses).
  Future<List<InspectionTask>> getMyReportHistory() async {
    try {
      final response = await _auth.dio.get('/api/inspections/my-reports');
      final List<dynamic> data = response.data['data'] ?? [];
      final tasks = data
          .map((e) => InspectionTask.fromJson(e as Map<String, dynamic>))
          .toList();
      final userId = await _auth.getAuthenticatedUserId();
      if (userId != null && userId.isNotEmpty) {
        await _saveLocalTasks(userId, tasks);
      }
      return tasks;
    } on DioException catch (e) {
      debugPrint(
        'InspectionService.getMyReportHistory (network failed): ${e.response?.data ?? e.message}',
      );
      try {
        final userId = await _auth.getAuthenticatedUserId();
        if (userId == null) return [];
        return await _queryLocalTasks(userId, activeOnly: false);
      } catch (ex) {
        debugPrint('InspectionService.local history fallback failed: $ex');
        return [];
      }
    }
  }

  /// Returns a relative `photoURL` for [submitInspection], or null on failure.
  /// Accepts either a local file path `String` or `XFile`.
  Future<String?> uploadEvidence(dynamic fileInput) async {
    String localPath;
    if (fileInput is XFile) {
      localPath = fileInput.path;
    } else if (fileInput is String) {
      localPath = fileInput;
    } else {
      return null;
    }

    final file = File(localPath);
    if (!await file.exists()) return null;

    final name = localPath.split(Platform.pathSeparator).last;
    final form = FormData.fromMap({
      'file': await MultipartFile.fromFile(localPath, filename: name),
    });

    final response = await _auth.dio.post(
      '/api/inspections/evidence',
      data: form,
    );
    return response.data['photoURL'] as String?;
  }

  /// Synchronize offline draft reports to backend.
  ///
  /// For each queued draft, any evidence photos captured while offline
  /// (stored as local file paths in [InspectionDraft.evidencePaths]) are
  /// uploaded first via [uploadEvidence]; the resulting server URLs are
  /// merged with any URLs that had already uploaded before the original
  /// failure. The report is only submitted once its evidence is fully on
  /// the server — if an upload fails mid-sync (e.g., signal drops again),
  /// the draft is marked [DraftStatus.failed] and will be retried on the
  /// next reconnect cycle instead of being submitted without proof.
  Future<int> syncPendingReports() async {
    if (_isSyncing) return 0;
    // No point syncing without a session — the backend would 401 every
    // draft (offline-restored sessions have no JWT until re-login).
    if (!_auth.isAuthenticated) return 0;
    _isSyncing = true;
    try {
      final drafts = await _offlineStorage.getDrafts();
      var synced = 0;
      for (final draft in drafts) {
        if (draft.id == null) continue;
        // 'failed' drafts are terminal (the server permanently rejected
        // them, e.g. assignment revoked while offline). They are kept for
        // manual review and are NOT retried here.
        if (draft.status == DraftStatus.failed) continue;
        await _offlineStorage.updateDraftStatus(draft.id!, DraftStatus.syncing);
        await refreshPendingDraftStatuses();
        try {
          // ── Re-upload offline-captured evidence photos ──────────────────
          final urls = <String>[];
          final existingPayload = draft.photoUrlPayload;
          if (existingPayload != null && existingPayload.isNotEmpty) {
            try {
              final decoded = jsonDecode(existingPayload);
              if (decoded is List) {
                urls.addAll(decoded.map((e) => e.toString()));
              }
            } catch (_) {
              // Unparseable payload — treat as no pre-uploaded URLs.
            }
          }

          var evidenceReady = true;
          for (final localPath in draft.evidencePaths) {
            try {
              final file = File(localPath);
              if (!await file.exists()) {
                // File vanished from the device; nothing to upload.
                continue;
              }
              final uploadedUrl = await uploadEvidence(localPath);
              if (uploadedUrl == null || uploadedUrl.isEmpty) {
                evidenceReady = false;
                break;
              }
              urls.add(uploadedUrl);
            } catch (_) {
              // Network dropped again mid-sync — retry on next cycle.
              evidenceReady = false;
              break;
            }
          }

          if (!evidenceReady) {
            // Retryable (network dropped mid-upload) — back to 'draft' so
            // the next reconnect cycle picks it up again.
            await _offlineStorage.updateDraftStatus(
                draft.id!, DraftStatus.draft);
            await refreshPendingDraftStatuses();
            continue;
          }

          await _auth.dio.post(
            '/api/inspections/submit',
            data: {
              'logID': draft.logId,
              'inspectionResult': draft.inspectionResult,
              'noticeLevel': draft.noticeLevel,
              'verifiedLat': draft.verifiedLat,
              'verifiedLng': draft.verifiedLng,
              'notes': draft.notes,
              'photoURL': urls.isEmpty ? null : jsonEncode(urls),
            },
          );
          await _offlineStorage.deleteDraft(draft.id!);
          synced++;
        } on DioException catch (e) {
          final code = e.response?.statusCode ?? 0;
          // 401/403 = auth problem (expired 12h token, or an offline-restored
          // session that has no JWT yet) — recoverable by re-logging in, so
          // the draft stays retryable. Other 4xx mean permanent rejection
          // (e.g. the assignment was revoked while offline) — mark terminal
          // so we stop hammering the API on every reconnect tick. Anything
          // network-level or 5xx also stays retryable.
          final terminal = code >= 400 &&
              code < 500 &&
              code != 401 &&
              code != 403 &&
              code != 408 &&
              code != 429;
          await _offlineStorage.updateDraftStatus(
            draft.id!,
            terminal ? DraftStatus.failed : DraftStatus.draft,
          );
        } catch (_) {
          await _offlineStorage.updateDraftStatus(draft.id!, DraftStatus.draft);
        }
        await refreshPendingDraftStatuses();
      }
      return synced;
    } catch (e) {
      debugPrint('InspectionService.syncPendingReports error: $e');
      return 0;
    } finally {
      _isSyncing = false;
    }
  }

  /// Get total count of unsynced offline draft reports.
  /// Terminal ('failed') drafts are excluded — they no longer participate
  /// in the auto-sync cycle.
  Future<int> getPendingDraftCount() async {
    try {
      final drafts = await _offlineStorage.getDrafts();
      return drafts.where((d) => d.status != DraftStatus.failed).length;
    } catch (e) {
      debugPrint('InspectionService.getPendingDraftCount error: $e');
      return 0;
    }
  }

  /// Submits the inspection report. Returns `true` if online submission succeeds,
  /// or `false` if an error occurs (or if processed offline).
  Future<bool> submitInspection({
    required InspectionTask task,
    required String inspectionResult,
    int noticeLevel = 0,
    String? notes,
    double? verifiedLat,
    double? verifiedLng,
    List<String>? evidenceLocalPaths,
    List<XFile>? evidenceFiles,
    List<String>? photoURLs,
  }) async {
    // Bookkeeping that must survive into the offline-draft catch block below:
    // finalUrls    = every photo URL confirmed on the server
    // pendingPaths = local files that still need uploading
    final List<String> finalUrls = [...(photoURLs ?? [])];
    final pendingPaths = <String>[];

    try {
      // Combine paths from strings or XFiles
      final List<dynamic> filesToUpload = [
        ...?evidenceLocalPaths,
        ...?evidenceFiles,
      ];

      if (filesToUpload.isNotEmpty) {
        // Upload concurrently, but track each result so a partially
        // successful upload batch is never lost.
        final uploaded = await Future.wait(
          filesToUpload.map((item) async {
            try {
              return await uploadEvidence(item);
            } catch (_) {
              return null;
            }
          }),
        );
        for (var i = 0; i < filesToUpload.length; i++) {
          final item = filesToUpload[i];
          final localPath = item is XFile ? item.path : item.toString();
          final url = uploaded[i];
          if (url != null && url.isNotEmpty) {
            finalUrls.add(url);
          } else {
            pendingPaths.add(localPath);
          }
        }
      }

      String? photoUrlPayload;
      if (finalUrls.isNotEmpty) {
        photoUrlPayload = jsonEncode(finalUrls);
      }

      await _auth.dio.post(
        '/api/inspections/submit',
        data: {
          'logID': task.logID,
          'inspectionResult': inspectionResult,
          'noticeLevel': noticeLevel,
          'verifiedLat': verifiedLat,
          'verifiedLng': verifiedLng,
          'notes': notes,
          'photoURL': photoUrlPayload,
        },
      );

      return true;
    } catch (e) {
      debugPrint('InspectionService.submitInspection error: $e');
      final now = DateTime.now().toUtc().toIso8601String();
      await _offlineStorage.saveDraft(
        InspectionDraft(
          logId: task.logID,
          reportId: task.reportID,
          inspectionResult: inspectionResult,
          notes: notes,
          noticeLevel: noticeLevel,
          verifiedLat: verifiedLat,
          verifiedLng: verifiedLng,
          // Only files that never made it to the server are queued;
          // URLs that uploaded successfully are preserved as-is.
          evidencePaths: pendingPaths,
          photoUrlPayload: finalUrls.isEmpty ? null : jsonEncode(finalUrls),
          createdAt: now,
          updatedAt: now,
          status: DraftStatus.draft,
        ),
      );
      await refreshPendingDraftStatuses();
      return false;
    }
  }

  /// Build absolute URL for evidence thumbnails (relative paths from API).
  static String? mediaAbsoluteUrl(String? path) {
    if (path == null || path.isEmpty) return null;
    if (path.startsWith('http')) return path;
    final base = ApiConfig.apiBase.replaceAll(RegExp(r'/$'), '');
    if (path.startsWith('/')) return '$base$path';
    return '$base/$path';
  }
}

class SyncNotification {
  final bool started;
  final int syncedCount;
  const SyncNotification.started() : started = true, syncedCount = 0;
  const SyncNotification.completed(this.syncedCount) : started = false;
}
