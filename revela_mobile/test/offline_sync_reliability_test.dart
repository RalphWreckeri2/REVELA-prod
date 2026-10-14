import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
// ignore: depend_on_referenced_packages
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:revela_mobile/service/auth_service.dart';
import 'package:revela_mobile/service/inspection_service.dart';
import 'package:revela_mobile/service/offline_inspection_storage.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _apiBase = 'https://inspection.test.invalid';

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({
    this.statusCode = 200,
    this.responseBody,
    this.historyBody,
    this.failureType,
    this.responseGate,
  });

  int statusCode;
  Map<String, dynamic>? responseBody;
  final Map<String, dynamic>? historyBody;
  DioExceptionType? failureType;
  final Completer<void>? responseGate;
  final List<RequestOptions> requests = [];
  final Completer<void> firstRequest = Completer<void>();

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (!firstRequest.isCompleted) firstRequest.complete();
    if (responseGate != null) await responseGate!.future;
    if (failureType != null) {
      throw DioException(requestOptions: options, type: failureType!);
    }
    final body =
        responseBody ??
        (options.uri.path.endsWith('/my-reports')
            ? (historyBody ?? {'data': <dynamic>[]})
            : {'reportID': options.data?['reportID'], 'status': 'Submitted'});
    return ResponseBody.fromString(
      jsonEncode(body),
      statusCode,
      headers: const {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _Harness {
  _Harness(this.directory, this.adapter, this.reachabilityCheck, this.now)
    : storage = OfflineInspectionStorage(
        databasePath: '${directory.path}\\inspection.db',
      ) {
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      secureValues,
    );
    final dio = Dio(BaseOptions(baseUrl: _apiBase))
      ..httpClientAdapter = adapter;
    auth = AuthService.forTesting(
      dio: dio,
      apiBase: _apiBase,
      tokenReader: () async => 'synthetic-test-token',
      clearSession: () async {},
      purgeAccount: () async {},
      clearLogoutSession: () async {},
      currentUser: const {'id': 'offline-test-inspector'},
    );
    service = InspectionService.forTesting(
      auth: auth,
      offlineStorage: storage,
      reachabilityCheck: reachabilityCheck,
      now: now,
    );
  }

  final Directory directory;
  final _FakeAdapter adapter;
  final Future<bool> Function() reachabilityCheck;
  final DateTime Function() now;
  final OfflineInspectionStorage storage;
  final Map<String, String> secureValues = {'authenticated_user_id': '9'};
  late final AuthService auth;
  late final InspectionService service;

  Future<void> close() async {
    await service.disposeForTesting();
    auth.dispose();
    await storage.close();
    await directory.delete(recursive: true);
  }
}

InspectionTask _task({
  int reportId = 100,
  int logId = 20,
  int? assignmentCycleId = 700,
}) => InspectionTask(
  reportID: reportId,
  assignmentCycleID: assignmentCycleId,
  logID: logId,
  detectedName: 'Sample Shop',
  barangayName: 'Sample Barangay',
  flagColor: 'Yellow',
  verificationStatus: 'Assigned',
  irTimestamp: '2026-10-12T10:00:00Z',
);

InspectionDraft _draft({
  int? id,
  int reportId = 100,
  int logId = 20,
  int? assignmentCycleId = 700,
  DraftStatus status = DraftStatus.draft,
  String ownerUserId = '9',
}) {
  final now = DateTime.now().toUtc().toIso8601String();
  return InspectionDraft(
    id: id,
    logId: logId,
    reportId: reportId,
    assignmentCycleID: assignmentCycleId,
    inspectionResult: 'Yellow',
    notes: 'Saved offline',
    noticeLevel: 0,
    evidencePaths: const [],
    createdAt: now,
    updatedAt: now,
    status: status,
    ownerUserId: ownerUserId,
  );
}

Future<List<InspectionDraft>> _ownedDrafts(_Harness harness) =>
    harness.storage.getDrafts(ownerUserId: '9');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  Future<_Harness> makeHarness({
    int statusCode = 200,
    Map<String, dynamic>? responseBody,
    Map<String, dynamic>? historyBody,
    DioExceptionType? failureType,
    Completer<void>? responseGate,
    Future<bool> Function()? reachabilityCheck,
    DateTime Function()? now,
  }) async {
    final directory = await Directory.systemTemp.createTemp(
      'revela_sync_test_',
    );
    return _Harness(
      directory,
      _FakeAdapter(
        statusCode: statusCode,
        responseBody: responseBody,
        historyBody: historyBody,
        failureType: failureType,
        responseGate: responseGate,
      ),
      reachabilityCheck ?? (() async => true),
      now ?? DateTime.now,
    );
  }

  test(
    'offline submit persists one draft and blocks the same report',
    () async {
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
      );
      addTearDown(harness.close);

      final first = await harness.service.submitInspection(
        task: _task(),
        inspectionResult: 'Yellow',
      );
      final second = await harness.service.submitInspection(
        task: _task(),
        inspectionResult: 'Red',
      );

      expect(first, InspectionSubmissionResult.savedOffline);
      expect(second, InspectionSubmissionResult.alreadySaved);
      expect(await _ownedDrafts(harness), hasLength(1));
      expect(harness.service.pendingDraftStatuses.value, {
        '100:700': DraftStatus.draft,
      });
    },
  );

  test(
    'offline retry preserves the original phone submission instant',
    () async {
      final phoneSubmittedAt = DateTime.utc(2025, 10, 13, 18, 46);
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
        now: () => phoneSubmittedAt,
      );
      addTearDown(harness.close);

      expect(
        await harness.service.submitInspection(
          task: _task(),
          inspectionResult: 'Yellow',
        ),
        InspectionSubmissionResult.savedOffline,
      );
      final pendingDraft = (await _ownedDrafts(harness)).single;
      final submittedAt = phoneSubmittedAt.toIso8601String();
      expect(pendingDraft.submittedAt, submittedAt);
      expect(harness.adapter.requests.single.data['submittedAt'], submittedAt);

      harness.adapter.failureType = null;
      harness.adapter.responseBody = {
        'reportID': 100,
        'status': 'Submitted',
        'submittedAt': submittedAt,
        'submissionReceivedAt': '2025-10-14 02:50:00',
      };
      expect(await harness.service.syncPendingReports(), 1);

      final retryPayload = harness.adapter.requests.last.data;
      expect(retryPayload['submittedAt'], submittedAt);
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test(
    'different assignment IDs for one business remain independently usable',
    () async {
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
      );
      addTearDown(harness.close);

      await harness.service.submitInspection(
        task: _task(reportId: 100, logId: 20),
        inspectionResult: 'Yellow',
      );
      final second = await harness.service.submitInspection(
        task: _task(reportId: 101, logId: 20),
        inspectionResult: 'Red',
      );

      expect(second, InspectionSubmissionResult.savedOffline);
      expect(
        (await _ownedDrafts(harness)).map((draft) => draft.reportId),
        containsAll([100, 101]),
      );
    },
  );

  test('inspection without a GPS fix still saves an offline draft', () async {
    final harness = await makeHarness(
      failureType: DioExceptionType.connectionError,
    );
    addTearDown(harness.close);

    final result = await harness.service.submitInspection(
      task: _task(),
      inspectionResult: 'Yellow',
      verifiedLat: null,
      verifiedLng: null,
      verifiedAccuracy: null,
    );

    final draft = (await _ownedDrafts(harness)).single;
    expect(result, InspectionSubmissionResult.savedOffline);
    expect(draft.verifiedLat, isNull);
    expect(draft.verifiedLng, isNull);
    expect(draft.verifiedAccuracy, isNull);
  });

  test(
    'offline drafts remain private and retryable across account changes',
    () async {
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
      );
      addTearDown(harness.close);

      expect(
        await harness.service.submitInspection(
          task: _task(),
          inspectionResult: 'Yellow',
        ),
        InspectionSubmissionResult.savedOffline,
      );
      final submissionsBeforeAccountSwitch = harness.adapter.requests
          .where((request) => request.uri.path.endsWith('/submit'))
          .length;

      harness.secureValues['authenticated_user_id'] = 'inspector-b';
      expect(await harness.service.getPendingDraftCount(), 0);
      expect(await harness.service.syncPendingReports(), 0);
      expect(
        harness.adapter.requests.where(
          (request) => request.uri.path.endsWith('/submit'),
        ),
        hasLength(submissionsBeforeAccountSwitch),
      );
      expect(await harness.service.getMyReportHistory(), isEmpty);

      harness.secureValues['authenticated_user_id'] = '9';
      final history = await harness.service.getMyReportHistory();
      expect(history, hasLength(1));
      expect(history.single.localDraftStatus, DraftStatus.draft);
      harness.adapter.failureType = null;
      expect(await harness.service.syncPendingReports(), 1);
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test('quarantined legacy drafts never appear or auto-sync', () async {
    final harness = await makeHarness();
    addTearDown(harness.close);
    final db = await harness.storage.database();
    final legacyData = _draft().toMap()..remove('id');
    await db.insert('inspection_drafts', {
      ...legacyData,
      'ownerUserId': '9',
      'isQuarantined': 1,
    });

    expect(await harness.service.getPendingDraftCount(), 0);
    expect(await harness.service.getMyReportHistory(), isEmpty);
    expect(await harness.service.syncPendingReports(), 0);
    expect(
      harness.adapter.requests.where(
        (request) => request.uri.path.endsWith('/submit'),
      ),
      isEmpty,
    );
    final retained = await db.query(
      'inspection_drafts',
      where: 'isQuarantined = 1',
    );
    expect(retained, hasLength(1));
    expect(retained.single['status'], DraftStatus.draft.name);
  });

  test('rapid concurrent submit calls only issue one request', () async {
    final gate = Completer<void>();
    final harness = await makeHarness(responseGate: gate);
    addTearDown(harness.close);

    final firstFuture = harness.service.submitInspection(
      task: _task(),
      inspectionResult: 'Yellow',
    );
    await harness.adapter.firstRequest.future;
    final second = await harness.service.submitInspection(
      task: _task(),
      inspectionResult: 'Yellow',
    );
    gate.complete();
    final first = await firstFuture;

    expect(first, InspectionSubmissionResult.submitted);
    expect(second, InspectionSubmissionResult.alreadySaved);
    expect(harness.adapter.requests, hasLength(1));
    expect(
      (harness.adapter.requests.single.data as Map)['assignmentCycleID'],
      700,
    );
  });

  test('pending draft and assignment lock survive storage restart', () async {
    final harness = await makeHarness(
      failureType: DioExceptionType.connectionTimeout,
    );
    final dbPath = '${harness.directory.path}\\inspection.db';
    await harness.service.submitInspection(
      task: _task(),
      inspectionResult: 'Yellow',
    );
    await harness.service.disposeForTesting();
    harness.auth.dispose();
    await harness.storage.close();

    final reopened = OfflineInspectionStorage(databasePath: dbPath);
    final restoredService = InspectionService.forTesting(
      auth: harness.auth,
      offlineStorage: reopened,
      reachabilityCheck: () async => false,
    );
    addTearDown(() async {
      await restoredService.disposeForTesting();
      await reopened.close();
      await harness.directory.delete(recursive: true);
    });
    final stored = await reopened.getDraftForReport(100, ownerUserId: '9');
    expect(stored?.status, DraftStatus.draft);
    expect(await reopened.getDrafts(ownerUserId: '9'), hasLength(1));
    expect(
      await restoredService.submitInspection(
        task: _task(),
        inspectionResult: 'Red',
      ),
      InspectionSubmissionResult.alreadySaved,
    );
  });

  test(
    'legacy assignment draft remains retryable without a cycle ID',
    () async {
      final harness = await makeHarness();
      addTearDown(harness.close);
      final legacy = _draft(assignmentCycleId: null);
      await harness.storage.saveDraft(legacy);

      final synced = await harness.service.syncPendingReports();

      expect(synced, 1);
      expect(harness.adapter.requests, hasLength(1));
      expect(harness.adapter.requests.single.data['assignmentCycleID'], isNull);
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test(
    'legacy draft appears in History as Pending Sync until accepted',
    () async {
      final harness = await makeHarness(
        historyBody: {
          'data': [_task().toJson()..['verificationStatus'] = 'Reassigned'],
        },
      );
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft(assignmentCycleId: null));

      final history = await harness.service.getMyReportHistory();

      expect(history, hasLength(2));
      final legacy = history.singleWhere(
        (task) => task.assignmentCycleID == null,
      );
      expect(legacy.localDraftStatus, DraftStatus.draft);
      expect(legacy.verificationStatus, 'Pending Sync');
      expect(legacy.remarks, 'Saved offline');
      expect(legacy.inspectionResult, 'Yellow');
    },
  );

  test('legacy draft does not block a distinct reassignment cycle', () async {
    final harness = await makeHarness(
      failureType: DioExceptionType.connectionError,
    );
    addTearDown(harness.close);
    final legacy = _draft(assignmentCycleId: null);
    await harness.storage.saveDraft(legacy);

    final result = await harness.service.submitInspection(
      task: _task(assignmentCycleId: 701),
      inspectionResult: 'Red',
    );

    expect(result, InspectionSubmissionResult.savedOffline);
    final drafts = await _ownedDrafts(harness);
    expect(drafts, hasLength(2));
    expect(
      drafts.map((draft) => draft.assignmentCycleID),
      containsAll([null, 701]),
    );
    expect(
      drafts.singleWhere((draft) => draft.assignmentCycleID == null).notes,
      legacy.notes,
    );
    await harness.service.refreshPendingDraftStatuses();
    expect(
      harness.service.pendingDraftStatuses.value['100:legacy'],
      DraftStatus.draft,
    );
    expect(
      harness.service.pendingDraftStatuses.value['100:701'],
      DraftStatus.draft,
    );
    expect(
      await harness.service.getDraftStatusForAssignment(100, 701),
      DraftStatus.draft,
    );
  });

  test('confirmed submission removes stale cached task from Current', () async {
    final harness = await makeHarness();
    addTearDown(harness.close);
    final db = await harness.storage.database();
    final task = _task();
    await db.insert('inspections', {
      'user_id': '9',
      'reportID': task.reportID,
      'logID': task.logID,
      'payload': jsonEncode(task.toJson()),
      'verificationStatus': 'Assigned',
      'flagColor': task.flagColor,
      'deadline': null,
    });

    await harness.storage.updateCachedTaskStatus(
      task.reportID,
      verificationStatus: 'Submitted',
      inspectionResult: 'Yellow',
      assignmentCycleID: task.assignmentCycleID,
      userId: '9',
    );

    expect(
      await harness.service.getLocalTasksForUser('9', activeOnly: true),
      isEmpty,
    );
    final history = await harness.service.getLocalTasksForUser(
      '9',
      activeOnly: false,
    );
    expect(history.single.verificationStatus, 'Submitted');
    expect(history.single.inspectionResult, 'Yellow');
  });

  test(
    'offline submission leaves Current and stays Pending Sync on refresh',
    () async {
      final task = _task(assignmentCycleId: null);
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
        responseBody: {
          'data': [task.toJson()],
        },
      );
      addTearDown(harness.close);
      final db = await harness.storage.database();
      await db.insert('inspections', {
        'user_id': '9',
        'reportID': task.reportID,
        'logID': task.logID,
        'payload': jsonEncode(task.toJson()),
        'verificationStatus': 'Assigned',
        'flagColor': task.flagColor,
        'deadline': null,
      });

      final result = await harness.service.submitInspection(
        task: task,
        inspectionResult: 'Yellow',
      );

      expect(result, InspectionSubmissionResult.savedOffline);
      expect(
        await harness.service.getLocalTasksForUser('9', activeOnly: true),
        isEmpty,
      );
      final history = await harness.service.getLocalTasksForUser(
        '9',
        activeOnly: false,
      );
      expect(history.single.verificationStatus, 'Pending Sync');

      harness.adapter.failureType = null;
      expect(await harness.service.getMyTasks(), isEmpty);

      harness.adapter.responseBody = null;
      expect(await harness.service.syncPendingReports(), 1);
      expect(harness.service.syncNotification.value?.syncedCount, 1);
      expect(await _ownedDrafts(harness), isEmpty);
      final submittedHistory = await harness.service.getLocalTasksForUser(
        '9',
        activeOnly: false,
      );
      expect(submittedHistory.single.verificationStatus, 'Submitted');
    },
  );

  test(
    'legacy duplicate drafts are retained and no third draft is added',
    () async {
      final harness = await makeHarness();
      addTearDown(harness.close);
      final db = await harness.storage.database();
      await db.insert('inspection_drafts', _draft().toMap()..remove('id'));
      await db.insert('inspection_drafts', _draft().toMap()..remove('id'));

      final savedId = await harness.storage.saveDraft(_draft());

      expect(savedId, greaterThan(0));
      expect(await _ownedDrafts(harness), hasLength(2));
    },
  );

  test('transient timeout retains draft for later retry', () async {
    final harness = await makeHarness(
      failureType: DioExceptionType.receiveTimeout,
    );
    addTearDown(harness.close);
    await harness.storage.saveDraft(_draft());

    expect(await harness.service.syncPendingReports(), 0);
    expect((await _ownedDrafts(harness)).single.status, DraftStatus.draft);
  });

  test('HTTP 5xx retains draft for controlled retry', () async {
    final harness = await makeHarness(statusCode: 503);
    addTearDown(harness.close);
    await harness.storage.saveDraft(_draft());

    expect(await harness.service.syncPendingReports(), 0);
    expect((await _ownedDrafts(harness)).single.status, DraftStatus.draft);
  });

  test(
    'permanent conflict becomes Needs Attention, not Pending Sync',
    () async {
      final harness = await makeHarness(
        statusCode: 409,
        responseBody: {'error': 'conflicting report'},
      );
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft());

      await harness.service.syncPendingReports();
      final history = await harness.service.getMyReportHistory();

      expect((await _ownedDrafts(harness)).single.status, DraftStatus.failed);
      expect(history.single.localDraftStatus, DraftStatus.failed);
      expect(history.single.verificationStatus, 'Needs Attention');
    },
  );

  test(
    'permission rejection needs attention without revoking the session',
    () async {
      final harness = await makeHarness(
        statusCode: 403,
        responseBody: {'error': 'Insufficient permissions'},
      );
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft());

      await harness.service.syncPendingReports();

      expect((await _ownedDrafts(harness)).single.status, DraftStatus.failed);
      expect(harness.auth.isAuthenticated, isTrue);
      expect(harness.auth.isAccountRevoked, isFalse);
    },
  );

  test(
    'lost response retry resubmits the same report identity and finalizes draft',
    () async {
      final harness = await makeHarness(
        failureType: DioExceptionType.connectionError,
      );
      addTearDown(harness.close);

      final saved = await harness.service.submitInspection(
        task: _task(),
        inspectionResult: 'Yellow',
        notes: 'Same accepted content',
      );
      expect(saved, InspectionSubmissionResult.savedOffline);
      final originalPayload = harness.adapter.requests.single.data;

      harness.adapter.failureType = null;
      await harness.service.syncPendingReports();

      expect(harness.adapter.requests, hasLength(2));
      expect(
        (harness.adapter.requests.last.data as Map)['reportID'],
        (originalPayload as Map)['reportID'],
      );
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test(
    'successful acknowledgement removes draft and retry triggers are serialized',
    () async {
      final gate = Completer<void>();
      final task = _task();
      final submittedTask = task.toJson()
        ..['verificationStatus'] = 'Submitted'
        ..['inspectionResult'] = 'Yellow';
      final harness = await makeHarness(
        responseGate: gate,
        historyBody: {
          'data': [submittedTask],
        },
      );
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft());

      final first = harness.service.syncPendingReports();
      await harness.adapter.firstRequest.future;
      final second = await harness.service.syncPendingReports();
      gate.complete();

      expect(await first, 1);
      expect(second, 0);
      expect(await _ownedDrafts(harness), isEmpty);
      expect(harness.adapter.requests, hasLength(1));
      expect(
        (harness.adapter.requests.single.data as Map)['assignmentCycleID'],
        700,
      );
      final history = await harness.service.getMyReportHistory();
      expect(history, hasLength(1));
      expect(history.single.reportID, task.reportID);
      expect(history.single.verificationStatus, 'Submitted');
    },
  );

  test(
    'authenticated reconnect automatically synchronizes pending reports',
    () async {
      var reachable = false;
      final harness = await makeHarness(
        reachabilityCheck: () async => reachable,
      );
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft());

      await harness.service.checkReconnectForTesting();
      expect(harness.adapter.requests, isEmpty);

      reachable = true;
      await harness.service.checkReconnectForTesting();

      expect(harness.adapter.requests, hasLength(1));
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test(
    'online sync retries transient server failure after bounded delay',
    () async {
      var now = DateTime.utc(2026, 10, 12);
      final harness = await makeHarness(statusCode: 503, now: () => now);
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft());

      await harness.service.checkReconnectForTesting();
      expect((await _ownedDrafts(harness)).single.status, DraftStatus.draft);

      harness.adapter.statusCode = 200;
      now = now.add(const Duration(seconds: 31));
      await harness.service.checkReconnectForTesting();

      expect(harness.adapter.requests, hasLength(2));
      expect(await _ownedDrafts(harness), isEmpty);
    },
  );

  test(
    'interrupted syncing state is restored as retryable after restart',
    () async {
      final harness = await makeHarness();
      addTearDown(harness.close);
      await harness.storage.saveDraft(_draft(status: DraftStatus.syncing));

      await harness.service.refreshPendingDraftStatuses();

      expect((await _ownedDrafts(harness)).single.status, DraftStatus.draft);
      expect(
        harness.service.pendingDraftStatuses.value['100:700'],
        DraftStatus.draft,
      );
    },
  );
}
