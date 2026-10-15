import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/auth_service.dart';
import 'package:revela_mobile/service/connectivity_service.dart';
import 'package:revela_mobile/service/flag_service.dart';
import 'package:revela_mobile/service/offline_inspection_storage.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class _FlagAdapter implements HttpClientAdapter {
  final List<RequestOptions> requests = [];
  DioExceptionType? failure;
  int statusCode = 201;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (failure != null) {
      throw DioException(requestOptions: options, type: failure!);
    }
    final isRegistry = options.path == '/api/registry/barangays';
    final Object body = isRegistry
        ? [
            {'barangayID': 2, 'barangayName': 'Barangay II'},
          ]
        : statusCode >= 400
        ? {'error': 'Coordinates do not fall within the selected barangay.'}
        : {
            'logID': 41,
            'lat': 13.960630,
            'lng': 121.113447,
            'alreadyAccepted': true,
          };
    return ResponseBody.fromString(
      jsonEncode(body),
      isRegistry ? 200 : statusCode,
      headers: const {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory directory;
  late OfflineInspectionStorage storage;
  late _FlagAdapter adapter;
  late AuthService auth;
  late FlagService flags;
  late String owner;
  late bool reachable;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    directory = await Directory.systemTemp.createTemp('revela_yellow_sync_');
    storage = OfflineInspectionStorage(
      databasePath: '${directory.path}/flags.db',
    );
    adapter = _FlagAdapter();
    owner = '9';
    reachable = true;
    ConnectivityService.instance.isOffline.value = false;
    const base = 'https://yellow-flags.test.invalid';
    final dio = Dio(BaseOptions(baseUrl: base))..httpClientAdapter = adapter;
    auth = AuthService.forTesting(
      dio: dio,
      apiBase: base,
      tokenReader: () async => 'synthetic-test-token',
      clearSession: () async {},
      purgeAccount: () async {},
      clearLogoutSession: () async {},
      currentUser: const {'id': '9'},
    );
    flags = FlagService.forTesting(
      auth,
      offlineStorage: storage,
      authenticatedUserId: () async => owner,
      backendReachable: () async => reachable,
    );
  });

  tearDown(() async {
    auth.dio.close(force: true);
    auth.dispose();
    await storage.close();
    await directory.delete(recursive: true);
  });

  Future<YellowFlagSubmissionResult> submit({int? barangayId = 2}) =>
      flags.submitYellowFlag(
        businessName: 'Sample Shop',
        lat: 13.960630,
        lng: 121.113447,
        barangayID: barangayId,
        barangayName: 'District II (Pob.)',
      );

  test(
    'offline Yellow Flag persists its owner and canonical retry UUID',
    () async {
      reachable = false;
      final result = await submit();
      expect(result.status, YellowFlagSubmissionStatus.pendingSync);
      expect(adapter.requests, isEmpty);
      final drafts = await flags.getMyYellowFlagDrafts();
      expect(drafts, hasLength(1));
      expect(drafts.single.ownerUserId, '9');
      expect(drafts.single.clientSubmissionId, result.clientSubmissionId);
      expect(
        result.clientSubmissionId,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
    },
  );

  test(
    'lost response retries the same UUID and confirms backend identity',
    () async {
      adapter.failure = DioExceptionType.connectionTimeout;
      final result = await submit();
      expect(result.status, YellowFlagSubmissionStatus.pendingSync);
      adapter.failure = null;
      final outcomes = await flags.syncPendingYellowFlags();
      expect(outcomes[result.clientSubmissionId]!.flag!.logID, 41);
      expect(await flags.getMyYellowFlagDrafts(), isEmpty);
      expect(adapter.requests, hasLength(2));
      for (final request in adapter.requests) {
        expect(request.path, '/api/flags/yellow');
        expect(request.data['clientSubmissionID'], result.clientSubmissionId);
        expect(request.data['expectedReporterUserID'], '9');
        expect(request.headers['Authorization'], 'Bearer synthetic-test-token');
      }
    },
  );

  test(
    'offline barangay names resolve to registry IDs before submission',
    () async {
      final result = await submit(barangayId: null);
      expect(result.status, YellowFlagSubmissionStatus.submitted);
      expect(adapter.requests.map((request) => request.path), [
        '/api/registry/barangays',
        '/api/flags/yellow',
      ]);
      expect(adapter.requests.last.data['barangayID'], 2);
    },
  );

  test(
    'validation rejection stays saved without repeated automatic submissions',
    () async {
      adapter.statusCode = 400;
      final result = await submit();
      expect(result.status, YellowFlagSubmissionStatus.needsAttention);
      final drafts = await flags.getMyYellowFlagDrafts();
      expect(drafts.single.status, YellowFlagDraftStatus.needsAttention);
      expect(drafts.single.lastError, contains('selected barangay'));
      expect(auth.isAuthenticated, isTrue);
      await flags.syncPendingYellowFlags();
      expect(adapter.requests, hasLength(1));
    },
  );

  test(
    'changing inspectors cannot read or submit another owners queue',
    () async {
      reachable = false;
      await submit();
      owner = '10';
      reachable = true;
      expect(await flags.getMyYellowFlagDrafts(), isEmpty);
      expect(await flags.syncPendingYellowFlags(), isEmpty);
      expect(adapter.requests, isEmpty);
      owner = '9';
      expect(await flags.getMyYellowFlagDrafts(), hasLength(1));
      await flags.syncPendingYellowFlags();
      expect(adapter.requests.single.data['expectedReporterUserID'], '9');
      expect(await flags.getMyYellowFlagDrafts(), isEmpty);
    },
  );
}
