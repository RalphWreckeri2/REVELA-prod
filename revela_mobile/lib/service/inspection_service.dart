import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

import 'api_config.dart';
import 'auth_service.dart';
import 'offline_inspection_storage.dart';
import '../utils/image_compressor.dart';

class InspectionTask {
  final int reportID;
  final int? assignmentCycleID;
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
  final String? dispatchedAt;
  final String? submittedAt;
  final String? submissionReceivedAt;

  /// Field result after inspector submits (null while still open).
  final String? inspectionResult;
  final String? deadline;
  final int currentNoticeLevel;
  final DraftStatus? localDraftStatus;

  String get assignmentKey => assignmentStatusKey(reportID, assignmentCycleID);

  InspectionTask({
    required this.reportID,
    this.assignmentCycleID,
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
    this.dispatchedAt,
    this.submittedAt,
    this.submissionReceivedAt,
    this.inspectionResult,
    this.deadline,
    this.currentNoticeLevel = 0,
    this.localDraftStatus,
  });

  factory InspectionTask.fromJson(Map<String, dynamic> json) {
    return InspectionTask(
      reportID: _asInt(json['reportID']),
      assignmentCycleID: json['assignmentCycleID'] == null
          ? null
          : _asInt(json['assignmentCycleID']),
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
      dispatchedAt: json['dispatchedAt']?.toString(),
      submittedAt: json['submittedAt']?.toString(),
      submissionReceivedAt: json['submissionReceivedAt']?.toString(),
      inspectionResult: json['inspectionResult']?.toString(),
      deadline: json['deadline']?.toString(),
      currentNoticeLevel: _asInt(json['currentNoticeLevel']),
      localDraftStatus: DraftStatus.values.cast<DraftStatus?>().firstWhere(
        (status) => status?.name == json['localDraftStatus'],
        orElse: () => null,
      ),
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
      'assignmentCycleID': assignmentCycleID,
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
      'dispatchedAt': dispatchedAt,
      'submittedAt': submittedAt,
      'submissionReceivedAt': submissionReceivedAt,
      'inspectionResult': inspectionResult,
      'deadline': deadline,
      'currentNoticeLevel': currentNoticeLevel,
      if (localDraftStatus != null) 'localDraftStatus': localDraftStatus!.name,
    };
  }

  InspectionTask withLocalDraftStatus(
    DraftStatus status, {
    String? submittedAt,
  }) => InspectionTask(
    reportID: reportID,
    assignmentCycleID: assignmentCycleID,
    logID: logID,
    detectedName: detectedName,
    barangayName: barangayName,
    flagColor: flagColor,
    verificationStatus: switch (status) {
      DraftStatus.draft => 'Pending Sync',
      DraftStatus.syncing => 'Syncing',
      DraftStatus.failed => 'Needs Attention',
      DraftStatus.synced => 'Submitted',
    },
    remarks: remarks,
    photoPath: photoPath,
    nearestLandmark: nearestLandmark,
    latitude: latitude,
    longitude: longitude,
    irTimestamp: irTimestamp,
    dispatchedAt: dispatchedAt,
    submittedAt: submittedAt ?? this.submittedAt,
    submissionReceivedAt: submissionReceivedAt,
    inspectionResult: inspectionResult,
    deadline: deadline,
    currentNoticeLevel: currentNoticeLevel,
    localDraftStatus: status,
  );
}

enum InspectionSubmissionResult {
  submitted,
  savedOffline,
  needsAttention,
  alreadySaved,
}

class InspectionService {
  static final InspectionService _instance = InspectionService._internal();
  factory InspectionService() => _instance;

  InspectionService._internal({
    AuthService? auth,
    OfflineInspectionStorage? offlineStorage,
    bool startReconnectMonitor = true,
    Future<bool> Function()? reachabilityCheck,
    DateTime Function()? now,
  }) : _auth = auth ?? AuthService(),
       _offlineStorage = offlineStorage ?? OfflineInspectionStorage(),
       _reachabilityCheck = reachabilityCheck ?? _defaultReachabilityCheck,
       _now = now ?? DateTime.now {
    if (startReconnectMonitor) _startReconnectMonitor();
  }

  @visibleForTesting
  InspectionService.forTesting({
    required AuthService auth,
    required OfflineInspectionStorage offlineStorage,
    Future<bool> Function()? reachabilityCheck,
    DateTime Function()? now,
  }) : this._internal(
         auth: auth,
         offlineStorage: offlineStorage,
         startReconnectMonitor: false,
         reachabilityCheck: reachabilityCheck,
         now: now,
       );

  final AuthService _auth;
  final OfflineInspectionStorage _offlineStorage;
  final Future<bool> Function() _reachabilityCheck;
  final DateTime Function() _now;
  final ValueNotifier<Map<String, DraftStatus>> pendingDraftStatuses =
      ValueNotifier<Map<String, DraftStatus>>({});
  final ValueNotifier<SyncNotification?> syncNotification =
      ValueNotifier<SyncNotification?>(null);
  Timer? _reconnectTimer;
  bool _wasReachable = false;
  bool _isSyncing = false;
  DateTime? _lastSyncAttemptAt;

  @visibleForTesting
  Future<void> disposeForTesting() async {
    _reconnectTimer?.cancel();
    pendingDraftStatuses.dispose();
    syncNotification.dispose();
  }

  static Future<bool> _defaultReachabilityCheck() async =>
      await ApiConfig.ensureReachable() != null;

  @visibleForTesting
  Future<void> checkReconnectForTesting() => _checkReconnect();

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
    final reachable = await _reachabilityCheck();
    final restored = reachable && !_wasReachable;
    _wasReachable = reachable;
    final hasPending = await getPendingDraftCount() > 0;
    final retryDue =
        _lastSyncAttemptAt == null ||
        _now().difference(_lastSyncAttemptAt!) >= const Duration(seconds: 30);
    if (reachable && hasPending && (restored || retryDue)) {
      _lastSyncAttemptAt = _now();
      syncNotification.value = const SyncNotification.started();
      await syncPendingReports();
    }
  }

  Future<void> refreshPendingDraftStatuses() async {
    final ownerUserId = await _auth.getAuthenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) {
      pendingDraftStatuses.value = {};
      return;
    }
    await _offlineStorage.recoverInterruptedSyncs(ownerUserId: ownerUserId);
    final drafts = await _offlineStorage.getDrafts(ownerUserId: ownerUserId);
    final statuses = <String, DraftStatus>{};
    for (final draft in drafts) {
      final current = statuses[draft.assignmentKey];
      if (current == null ||
          _draftStatusPriority(draft.status) > _draftStatusPriority(current)) {
        statuses[draft.assignmentKey] = draft.status;
      }
    }
    pendingDraftStatuses.value = statuses;
  }

  static int _draftStatusPriority(DraftStatus status) => switch (status) {
    DraftStatus.syncing => 3,
    DraftStatus.failed => 2,
    DraftStatus.draft => 1,
    DraftStatus.synced => 0,
  };

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
    String? requestUserId;
    try {
      requestUserId = await _auth.getAuthenticatedUserId();
      final response = await _auth.dio.get('/api/inspections/tasks');
      if (requestUserId != await _auth.getAuthenticatedUserId()) return [];
      final List<dynamic> data = response.data['data'] ?? [];
      final serverTasks = data
          .map((e) => InspectionTask.fromJson(e as Map<String, dynamic>))
          .toList();
      final pendingDrafts = requestUserId == null || requestUserId.isEmpty
          ? <InspectionDraft>[]
          : await _offlineStorage.getDrafts(ownerUserId: requestUserId);
      if (requestUserId != await _auth.getAuthenticatedUserId()) return [];
      final pendingAssignmentKeys = pendingDrafts
          .map((draft) => draft.assignmentKey)
          .toSet();
      final tasks = serverTasks
          .where((task) => !pendingAssignmentKeys.contains(task.assignmentKey))
          .toList();
      if (requestUserId != null && requestUserId.isNotEmpty) {
        await _saveLocalTasks(requestUserId, tasks);
      }
      if (requestUserId != await _auth.getAuthenticatedUserId()) return [];
      return tasks;
    } on DioException catch (e) {
      debugPrint(
        'InspectionService.getMyTasks (network failed): ${e.response?.data ?? e.message}',
      );
      // Fallback to local DB filtered by authenticated_user_id
      try {
        final userId = await _auth.getAuthenticatedUserId();
        if (requestUserId != userId) return [];
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
        uid = await _auth.getAuthenticatedUserId();
        if (uid == null || uid.isEmpty) {
          debugPrint(
            'getLocalTasksForUser: no userId provided and no authenticated_user_id found',
          );
          return [];
        }
      }
      if (uid != await _auth.getAuthenticatedUserId()) return [];
      // Ensure we pass a string representation to the SQL query
      return await _queryLocalTasks(uid.toString(), activeOnly: activeOnly);
    } catch (e) {
      debugPrint('getLocalTasksForUser failed: $e');
      return [];
    }
  }

  /// Full history for the logged-in inspector (all statuses).
  Future<List<InspectionTask>> getMyReportHistory() async {
    String? requestUserId;
    try {
      requestUserId = await _auth.getAuthenticatedUserId();
      final response = await _auth.dio.get('/api/inspections/my-reports');
      if (requestUserId != await _auth.getAuthenticatedUserId()) return [];
      final List<dynamic> data = response.data['data'] ?? [];
      var tasks = data
          .map((e) => InspectionTask.fromJson(e as Map<String, dynamic>))
          .toList();
      if (requestUserId != null && requestUserId.isNotEmpty) {
        await _saveLocalTasks(requestUserId, tasks);
      }
      tasks = await _mergePendingDrafts(tasks, requestUserId);
      if (requestUserId != await _auth.getAuthenticatedUserId()) return [];
      return tasks;
    } on DioException catch (e) {
      debugPrint(
        'InspectionService.getMyReportHistory (network failed): ${e.response?.data ?? e.message}',
      );
      try {
        final userId = await _auth.getAuthenticatedUserId();
        if (requestUserId != userId) return [];
        if (userId == null) return [];
        final tasks = await _queryLocalTasks(userId, activeOnly: false);
        return _mergePendingDrafts(tasks, userId);
      } catch (ex) {
        debugPrint('InspectionService.local history fallback failed: $ex');
        return [];
      }
    }
  }

  Future<List<InspectionTask>> _mergePendingDrafts(
    List<InspectionTask> history,
    String? userId,
  ) async {
    await refreshPendingDraftStatuses();
    final drafts = userId == null || userId.isEmpty
        ? <InspectionDraft>[]
        : await _offlineStorage.getDrafts(ownerUserId: userId);
    if (drafts.isEmpty) return history;
    final merged = [...history];
    List<InspectionTask>? cachedTasks;
    for (final draft in drafts) {
      final existingIndex = merged.indexWhere(
        (task) => task.assignmentKey == draft.assignmentKey,
      );
      if (existingIndex >= 0) {
        final task = merged[existingIndex];
        merged[existingIndex] = task.withLocalDraftStatus(
          draft.status,
          submittedAt:
              const {'Submitted', 'Verified'}.contains(task.verificationStatus)
              ? task.submittedAt
              : draft.submittedAt,
        );
        continue;
      }
      cachedTasks ??= await getLocalTasksForUser(userId, activeOnly: false);
      final cached = cachedTasks.where(
        (task) => task.assignmentKey == draft.assignmentKey,
      );
      final task = cached.isEmpty
          ? InspectionTask(
              reportID: draft.reportId,
              assignmentCycleID: draft.assignmentCycleID,
              logID: draft.logId,
              detectedName: 'Inspection report',
              barangayName: 'Unknown Barangay',
              flagColor: 'Grey',
              verificationStatus: 'Pending Sync',
              irTimestamp: '',
              submittedAt: draft.submittedAt,
              inspectionResult: draft.inspectionResult,
              remarks: draft.notes,
              photoPath: draft.photoUrlPayload,
            )
          : cached.first;
      merged.add(
        task.withLocalDraftStatus(
          draft.status,
          submittedAt:
              const {'Submitted', 'Verified'}.contains(task.verificationStatus)
              ? task.submittedAt
              : draft.submittedAt,
        ),
      );
    }
    return merged;
  }

  Future<DraftStatus?> getDraftStatusForAssignment(
    int reportId,
    int? assignmentCycleID,
  ) async {
    final ownerUserId = await _auth.getAuthenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) return null;
    return (await _offlineStorage.getDraftForAssignment(
      reportId,
      assignmentCycleID,
      ownerUserId: ownerUserId,
    ))?.status;
  }

  /// Returns a relative `photoURL` for [submitInspection], or null on failure.
  /// Accepts either a local file path `String`, `File`, or `XFile`.
  Future<String?> uploadEvidence(dynamic fileInput) async {
    String localPath;
    if (fileInput is XFile) {
      localPath = fileInput.path;
    } else if (fileInput is String) {
      localPath = fileInput;
    } else if (fileInput is File) {
      localPath = fileInput.path;
    } else {
      return null;
    }

    final rawFile = File(localPath);
    if (!await rawFile.exists()) return null;

    final compressedFile = await compressImageFile(rawFile);
    final uploadPath = compressedFile.path;

    final name = uploadPath.split(Platform.pathSeparator).last;
    final form = FormData.fromMap({
      'file': await MultipartFile.fromFile(uploadPath, filename: name),
    });

    final response = await _auth.dio.post(
      '/api/inspections/evidence',
      data: form,
    );
    return response.data['photoURL'] as String?;
  }

  /// Synchronize persisted drafts. An in-progress upload is checkpointed
  /// before submitting so a lost response does not upload evidence again.
  Future<int> syncPendingReports() async {
    if (_isSyncing) return 0;
    if (!_auth.isAuthenticated) return 0;
    final ownerUserId = await _auth.getAuthenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) return 0;
    _isSyncing = true;
    try {
      await _offlineStorage.recoverInterruptedSyncs(ownerUserId: ownerUserId);
      final drafts = await _offlineStorage.getDrafts(ownerUserId: ownerUserId);
      var synced = 0;
      for (final draft in drafts) {
        if (draft.id == null) continue;
        if (draft.status == DraftStatus.failed) continue;
        if (!await _isCurrentDraftOwner(ownerUserId)) break;
        await _offlineStorage.updateDraftStatus(
          draft.id!,
          DraftStatus.syncing,
          ownerUserId: ownerUserId,
        );
        await refreshPendingDraftStatuses();
        try {
          final urls = <String>[];
          final existingPayload = draft.photoUrlPayload;
          if (existingPayload != null && existingPayload.isNotEmpty) {
            try {
              final decoded = jsonDecode(existingPayload);
              if (decoded is List) {
                urls.addAll(decoded.map((e) => e.toString()));
              }
            } catch (_) {
              await _offlineStorage.updateDraftStatus(
                draft.id!,
                DraftStatus.failed,
                ownerUserId: ownerUserId,
              );
              await refreshPendingDraftStatuses();
              continue;
            }
          }

          var evidenceReady = true;
          var missingEvidence = false;
          final remainingPaths = <String>[];
          for (final localPath in draft.evidencePaths) {
            try {
              if (!await _isCurrentDraftOwner(ownerUserId)) {
                evidenceReady = false;
                remainingPaths.add(localPath);
                break;
              }
              final file = File(localPath);
              if (!await file.exists()) {
                missingEvidence = true;
                remainingPaths.add(localPath);
                continue;
              }
              final uploadedUrl = await uploadEvidence(localPath);
              if (uploadedUrl == null || uploadedUrl.isEmpty) {
                evidenceReady = false;
                remainingPaths.add(localPath);
                continue;
              }
              urls.add(uploadedUrl);
            } catch (_) {
              evidenceReady = false;
              remainingPaths.add(localPath);
            }
          }

          final preparedDraft = InspectionDraft(
            id: draft.id,
            logId: draft.logId,
            reportId: draft.reportId,
            assignmentCycleID: draft.assignmentCycleID,
            inspectionResult: draft.inspectionResult,
            notes: draft.notes,
            noticeLevel: draft.noticeLevel,
            verifiedLat: draft.verifiedLat,
            verifiedLng: draft.verifiedLng,
            verifiedAccuracy: draft.verifiedAccuracy,
            evidencePaths: remainingPaths,
            photoUrlPayload: urls.isEmpty ? null : jsonEncode(urls),
            submittedAt: draft.submittedAt,
            createdAt: draft.createdAt,
            updatedAt: DateTime.now().toUtc().toIso8601String(),
            status: missingEvidence ? DraftStatus.failed : DraftStatus.syncing,
            ownerUserId: ownerUserId,
          );
          await _offlineStorage.saveDraft(preparedDraft);

          if (missingEvidence) {
            await refreshPendingDraftStatuses();
            continue;
          }
          if (!evidenceReady) {
            await _offlineStorage.updateDraftStatus(
              draft.id!,
              DraftStatus.draft,
              ownerUserId: ownerUserId,
            );
            await refreshPendingDraftStatuses();
            if (!await _isCurrentDraftOwner(ownerUserId)) break;
            continue;
          }
          if (!await _isCurrentDraftOwner(ownerUserId)) {
            await _offlineStorage.updateDraftStatus(
              draft.id!,
              DraftStatus.draft,
              ownerUserId: ownerUserId,
            );
            await refreshPendingDraftStatuses();
            break;
          }

          final response = await _auth.dio.post(
            '/api/inspections/submit',
            data: {
              'reportID': draft.reportId,
              if (draft.assignmentCycleID != null)
                'assignmentCycleID': draft.assignmentCycleID,
              'logID': draft.logId,
              'inspectionResult': draft.inspectionResult,
              if (draft.submittedAt != null) 'submittedAt': draft.submittedAt,
              'noticeLevel': draft.noticeLevel,
              'verifiedLat': draft.verifiedLat,
              'verifiedLng': draft.verifiedLng,
              'verifiedAccuracy': draft.verifiedAccuracy,
              'notes': draft.notes,
              'photoURL': urls.isEmpty ? null : jsonEncode(urls),
            },
          );
          if (!_isAcceptedSubmission(response.data, draft.reportId)) {
            throw const FormatException(
              'Submission response did not confirm the report identity.',
            );
          }
          await _offlineStorage.updateCachedTaskStatus(
            draft.reportId,
            verificationStatus: 'Submitted',
            inspectionResult: draft.inspectionResult,
            submittedAt: response.data is Map
                ? response.data['submittedAt']?.toString()
                : null,
            submissionReceivedAt: response.data is Map
                ? response.data['submissionReceivedAt']?.toString()
                : null,
            replaceSubmittedAt:
                response.data is Map &&
                response.data.containsKey('submittedAt'),
            replaceSubmissionReceivedAt:
                response.data is Map &&
                response.data.containsKey('submissionReceivedAt'),
            assignmentCycleID: draft.assignmentCycleID,
            userId: ownerUserId,
          );
          await _offlineStorage.deleteDraft(
            draft.id!,
            ownerUserId: ownerUserId,
          );
          synced++;
        } on DioException catch (e) {
          final code = e.response?.statusCode ?? 0;
          final terminal =
              code >= 400 &&
              code < 500 &&
              code != 401 &&
              code != 408 &&
              code != 429;
          await _offlineStorage.updateDraftStatus(
            draft.id!,
            terminal ? DraftStatus.failed : DraftStatus.draft,
            ownerUserId: ownerUserId,
          );
        } catch (_) {
          await _offlineStorage.updateDraftStatus(
            draft.id!,
            DraftStatus.draft,
            ownerUserId: ownerUserId,
          );
        }
        await refreshPendingDraftStatuses();
      }
      if (synced > 0) {
        syncNotification.value = SyncNotification.completed(synced);
      } else if (await getPendingDraftCount() > 0) {
        syncNotification.value = const SyncNotification.retryScheduled();
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
      final ownerUserId = await _auth.getAuthenticatedUserId();
      if (ownerUserId == null || ownerUserId.isEmpty) return 0;
      final drafts = await _offlineStorage.getDrafts(ownerUserId: ownerUserId);
      return drafts.where((d) => d.status != DraftStatus.failed).length;
    } catch (e) {
      debugPrint('InspectionService.getPendingDraftCount error: $e');
      return 0;
    }
  }

  Future<bool> _isCurrentDraftOwner(String ownerUserId) async =>
      _auth.isAuthenticated &&
      await _auth.getAuthenticatedUserId() == ownerUserId;

  static bool _isAcceptedSubmission(dynamic data, int reportId) {
    if (data is! Map) return false;
    final responseId = int.tryParse(data['reportID']?.toString() ?? '');
    final status = data['status']?.toString().toLowerCase();
    return responseId == reportId &&
        (data['alreadyAccepted'] == true ||
            status == 'submitted' ||
            status == 'verified');
  }

  Future<void> _persistDraft({
    required String ownerUserId,
    required InspectionTask task,
    required String submittedAt,
    required String inspectionResult,
    required int noticeLevel,
    required String? notes,
    required double? verifiedLat,
    required double? verifiedLng,
    required double? verifiedAccuracy,
    required List<String> evidencePaths,
    required List<String> photoUrls,
    required DraftStatus status,
  }) async {
    final now = _now().toUtc().toIso8601String();
    if (ownerUserId.isEmpty) {
      throw StateError(
        'An authenticated inspector is required to save an inspection draft.',
      );
    }
    await _offlineStorage.saveDraft(
      InspectionDraft(
        logId: task.logID,
        reportId: task.reportID,
        assignmentCycleID: task.assignmentCycleID,
        inspectionResult: inspectionResult,
        notes: notes,
        noticeLevel: noticeLevel,
        verifiedLat: verifiedLat,
        verifiedLng: verifiedLng,
        verifiedAccuracy: verifiedAccuracy,
        evidencePaths: evidencePaths,
        photoUrlPayload: photoUrls.isEmpty ? null : jsonEncode(photoUrls),
        submittedAt: submittedAt,
        createdAt: now,
        updatedAt: now,
        status: status,
        ownerUserId: ownerUserId,
      ),
    );
    await _offlineStorage.updateCachedTaskStatus(
      task.reportID,
      verificationStatus: status == DraftStatus.failed
          ? 'Needs Attention'
          : 'Pending Sync',
      inspectionResult: inspectionResult,
      submittedAt: submittedAt,
      assignmentCycleID: task.assignmentCycleID,
      userId: ownerUserId,
    );
    await refreshPendingDraftStatuses();
  }

  Future<InspectionSubmissionResult> submitInspection({
    required InspectionTask task,
    required String inspectionResult,
    int noticeLevel = 0,
    String? notes,
    double? verifiedLat,
    double? verifiedLng,
    double? verifiedAccuracy,
    List<String>? evidenceLocalPaths,
    List<XFile>? evidenceFiles,
    List<String>? photoURLs,
    void Function(String? requestId, int? status, bool alreadyAccepted)?
        onCommittedResponse,
    void Function(String? requestId, int? status)? onResponse,
    void Function(String? requestId, int? status)? onRequestFailure,
  }) async {
    final ownerUserId = await _auth.getAuthenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) {
      throw StateError(
        'An authenticated inspector is required to submit an inspection.',
      );
    }
    final submittedAt = _now().toUtc().toIso8601String();
    final assignmentKey = '$ownerUserId:${task.assignmentKey}';
    if (!_submittingAssignmentKeys.add(assignmentKey)) {
      return InspectionSubmissionResult.alreadySaved;
    }
    try {
      if (await _offlineStorage.getDraftForAssignment(
            task.reportID,
            task.assignmentCycleID,
            ownerUserId: ownerUserId,
          ) !=
          null) {
        await refreshPendingDraftStatuses();
        _submittingAssignmentKeys.remove(assignmentKey);
        return InspectionSubmissionResult.alreadySaved;
      }
    } catch (error) {
      _submittingAssignmentKeys.remove(assignmentKey);
      rethrow;
    }
    final List<String> finalUrls = [...(photoURLs ?? <String>[])];
    final pendingPaths = <String>[];
    var missingEvidence = false;

    try {
      final List<dynamic> filesToUpload = [
        ...?evidenceLocalPaths,
        ...?evidenceFiles,
      ];

      for (final item in filesToUpload) {
        final localPath = item is XFile ? item.path : item.toString();
        if (!await _isCurrentDraftOwner(ownerUserId)) {
          pendingPaths.add(localPath);
          continue;
        }
        if (!await File(localPath).exists()) {
          missingEvidence = true;
          pendingPaths.add(localPath);
          continue;
        }
        try {
          final url = await uploadEvidence(item);
          if (url == null || url.isEmpty) {
            pendingPaths.add(localPath);
          } else {
            finalUrls.add(url);
          }
        } catch (_) {
          pendingPaths.add(localPath);
        }
      }

      if (pendingPaths.isNotEmpty) {
        final status = missingEvidence ? DraftStatus.failed : DraftStatus.draft;
        await _persistDraft(
          ownerUserId: ownerUserId,
          task: task,
          submittedAt: submittedAt,
          inspectionResult: inspectionResult,
          noticeLevel: noticeLevel,
          notes: notes,
          verifiedLat: verifiedLat,
          verifiedLng: verifiedLng,
          verifiedAccuracy: verifiedAccuracy,
          evidencePaths: pendingPaths,
          photoUrls: finalUrls,
          status: status,
        );
        return missingEvidence
            ? InspectionSubmissionResult.needsAttention
            : InspectionSubmissionResult.savedOffline;
      }

      if (!await _isCurrentDraftOwner(ownerUserId)) {
        throw StateError(
          'Inspector session changed during inspection submission.',
        );
      }
      final photoUrlPayload = finalUrls.isEmpty ? null : jsonEncode(finalUrls);
      final response = await _auth.dio.post(
        '/api/inspections/submit',
        data: {
          'reportID': task.reportID,
          if (task.assignmentCycleID != null)
            'assignmentCycleID': task.assignmentCycleID,
          'logID': task.logID,
          'inspectionResult': inspectionResult,
          'submittedAt': submittedAt,
          'noticeLevel': noticeLevel,
          'verifiedLat': verifiedLat,
          'verifiedLng': verifiedLng,
          'verifiedAccuracy': verifiedAccuracy,
          'notes': notes,
          'photoURL': photoUrlPayload,
        },
      );
      onResponse?.call(response.headers.value('x-request-id'), response.statusCode);
      if (!_isAcceptedSubmission(response.data, task.reportID)) {
        throw const FormatException(
          'Submission response did not confirm the report identity.',
        );
      }
      onCommittedResponse?.call(
        response.headers.value('x-request-id'), response.statusCode,
        response.data is Map && response.data['alreadyAccepted'] == true,
      );
      await _offlineStorage.updateCachedTaskStatus(
        task.reportID,
        verificationStatus: 'Submitted',
        inspectionResult: inspectionResult,
        submittedAt: response.data is Map
            ? response.data['submittedAt']?.toString()
            : null,
        submissionReceivedAt: response.data is Map
            ? response.data['submissionReceivedAt']?.toString()
            : null,
        replaceSubmittedAt:
            response.data is Map && response.data.containsKey('submittedAt'),
        replaceSubmissionReceivedAt:
            response.data is Map &&
            response.data.containsKey('submissionReceivedAt'),
        assignmentCycleID: task.assignmentCycleID,
        userId: ownerUserId,
      );
      return InspectionSubmissionResult.submitted;
    } catch (error) {
      if (error is DioException) {
        onRequestFailure?.call(
          error.response?.headers.value('x-request-id'),
          error.response?.statusCode,
        );
      }
      debugPrint('InspectionService.submitInspection failed: $error');
      final responseCode = error is DioException
          ? error.response?.statusCode ?? 0
          : 0;
      final terminal =
          missingEvidence ||
          (responseCode >= 400 &&
              responseCode < 500 &&
              responseCode != 401 &&
              responseCode != 408 &&
              responseCode != 429);
      await _persistDraft(
        ownerUserId: ownerUserId,
        task: task,
        submittedAt: submittedAt,
        inspectionResult: inspectionResult,
        noticeLevel: noticeLevel,
        notes: notes,
        verifiedLat: verifiedLat,
        verifiedLng: verifiedLng,
        verifiedAccuracy: verifiedAccuracy,
        evidencePaths: pendingPaths,
        photoUrls: finalUrls,
        status: terminal ? DraftStatus.failed : DraftStatus.draft,
      );
      return terminal
          ? InspectionSubmissionResult.needsAttention
          : InspectionSubmissionResult.savedOffline;
    } finally {
      _submittingAssignmentKeys.remove(assignmentKey);
    }
  }

  final Set<String> _submittingAssignmentKeys = {};

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
  final bool retryScheduled;
  const SyncNotification.started()
    : started = true,
      syncedCount = 0,
      retryScheduled = false;
  const SyncNotification.completed(this.syncedCount)
    : started = false,
      retryScheduled = false;
  const SyncNotification.retryScheduled()
    : started = false,
      syncedCount = 0,
      retryScheduled = true;
}
