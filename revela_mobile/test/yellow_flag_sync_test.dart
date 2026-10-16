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

  Future<YellowFlagSubmissionResult> submit({
    int? barangayId = 2,
    YellowFlagLocationMethod method = YellowFlagLocationMethod.manualPin,
  }) => flags.submitYellowFlag(
    businessName: 'Sample Shop',
    businessAddress: 'Purok Makisig, behind the unnamed chapel',
    locationMethod: method,
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
      expect(
        drafts.single.businessAddress,
        'Purok Makisig, behind the unnamed chapel',
      );
      expect(drafts.single.lat, 13.960630);
      expect(drafts.single.lng, 121.113447);
      expect(drafts.single.locationMethod, YellowFlagLocationMethod.manualPin);
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
        expect(
          request.data['businessAddress'],
          'Purok Makisig, behind the unnamed chapel',
        );
        expect(request.data['lat'], 13.960630);
        expect(request.data['lng'], 121.113447);
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

  test('offline address and business pin survive restart and sync', () async {
    reachable = false;
    final result = await submit(method: YellowFlagLocationMethod.address);
    await storage.close();
    final restarted = OfflineInspectionStorage(
      databasePath: '${directory.path}/flags.db',
    );
    try {
      final restartedFlags = FlagService.forTesting(
        auth,
        offlineStorage: restarted,
        authenticatedUserId: () async => owner,
        backendReachable: () async => reachable,
      );
      final drafts = await restartedFlags.getMyYellowFlagDrafts();
      expect(
        drafts.single.businessAddress,
        'Purok Makisig, behind the unnamed chapel',
      );
      expect(drafts.single.lat, 13.960630);
      expect(drafts.single.lng, 121.113447);
      expect(drafts.single.locationMethod, YellowFlagLocationMethod.address);
      reachable = true;
      final outcomes = await restartedFlags.syncPendingYellowFlags();
      final synced = outcomes[result.clientSubmissionId]!.flag!;
      expect(
        synced.businessAddress,
        'Purok Makisig, behind the unnamed chapel',
      );
      expect(synced.lat, 13.960630);
      expect(synced.lng, 121.113447);
      expect(
        adapter.requests.single.data['businessAddress'],
        'Purok Makisig, behind the unnamed chapel',
      );
      expect(adapter.requests.single.data['lat'], 13.960630);
      expect(adapter.requests.single.data['lng'], 121.113447);
      expect(
        adapter.requests.single.data['clientSubmissionID'],
        result.clientSubmissionId,
      );
      expect(await restartedFlags.getMyYellowFlagDrafts(), isEmpty);
    } finally {
      await restarted.close();
    }
  });

  test('v8 Yellow Flag queue upgrades without losing legacy reports', () async {
    final path = '${directory.path}/legacy.db';
    final legacy = await databaseFactory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 8,
        onCreate: (db, _) async {
          await db.execute('''
            CREATE TABLE yellow_flag_drafts (
              clientSubmissionId TEXT NOT NULL, ownerUserId TEXT NOT NULL,
              businessName TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
              barangayId INTEGER, barangayName TEXT NOT NULL, notes TEXT,
              createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL,
              status TEXT NOT NULL, lastError TEXT,
              PRIMARY KEY (ownerUserId, clientSubmissionId)
            )
          ''');
          await db.insert('yellow_flag_drafts', {
            'clientSubmissionId': 'legacy-report',
            'ownerUserId': '9',
            'businessName': 'Legacy Shop',
            'lat': 13.960630,
            'lng': 121.113447,
            'barangayId': 2,
            'barangayName': 'Barangay II',
            'notes': 'Keep me',
            'createdAt': '2026-10-15',
            'updatedAt': '2026-10-15',
            'status': 'pendingSync',
          });
        },
      ),
    );
    await legacy.close();
    final upgraded = OfflineInspectionStorage(databasePath: path);
    try {
      final drafts = await upgraded.getYellowFlagDrafts(ownerUserId: '9');
      expect(drafts, hasLength(1));
      expect(drafts.single.businessAddress, isNull);
      expect(
        drafts.single.locationMethod,
        YellowFlagLocationMethod.savedReport,
      );
      expect(drafts.single.businessName, 'Legacy Shop');
      expect(drafts.single.notes, 'Keep me');
      expect(drafts.single.lat, 13.960630);
      expect(drafts.single.lng, 121.113447);
      await upgraded.saveYellowFlagDraft(
        YellowFlagDraft(
          clientSubmissionId: 'new-report',
          ownerUserId: '9',
          businessName: 'New Shop',
          businessAddress: 'Unnamed purok',
          locationMethod: YellowFlagLocationMethod.manualPin,
          lat: 13.960630,
          lng: 121.113447,
          barangayId: 2,
          barangayName: 'Barangay II',
          notes: null,
          createdAt: '2026-10-16',
          updatedAt: '2026-10-16',
          status: YellowFlagDraftStatus.pendingSync,
        ),
      );
      expect(
        await upgraded.getYellowFlagDrafts(ownerUserId: '9'),
        hasLength(2),
      );
      expect(
        (await upgraded.getYellowFlagDrafts(ownerUserId: '9'))
            .firstWhere((draft) => draft.clientSubmissionId == 'new-report')
            .locationMethod,
        YellowFlagLocationMethod.manualPin,
      );
    } finally {
      await upgraded.close();
    }
  });

  test(
    'v9 queue gains location provenance without changing address or coordinates',
    () async {
      final path = '${directory.path}/v9.db';
      final legacy = await databaseFactory.openDatabase(
        path,
        options: OpenDatabaseOptions(
          version: 9,
          onCreate: (db, _) async {
            await db.execute('''
          CREATE TABLE yellow_flag_drafts (
            clientSubmissionId TEXT NOT NULL, ownerUserId TEXT NOT NULL,
            businessName TEXT NOT NULL, businessAddress TEXT,
            lat REAL NOT NULL, lng REAL NOT NULL, barangayId INTEGER,
            barangayName TEXT NOT NULL, notes TEXT, createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL, status TEXT NOT NULL, lastError TEXT,
            PRIMARY KEY (ownerUserId, clientSubmissionId)
          )
        ''');
            await db.insert('yellow_flag_drafts', {
              'clientSubmissionId': 'v9-report',
              'ownerUserId': '9',
              'businessName': 'Existing Shop',
              'businessAddress': 'Keep this typed address',
              'lat': 13.960630,
              'lng': 121.113447,
              'barangayId': 2,
              'barangayName': 'Barangay II',
              'notes': 'Keep these notes',
              'createdAt': '2026-10-16',
              'updatedAt': '2026-10-16',
              'status': 'pendingSync',
            });
          },
        ),
      );
      await legacy.close();
      final upgraded = OfflineInspectionStorage(databasePath: path);
      try {
        final draft = (await upgraded.getYellowFlagDrafts(
          ownerUserId: '9',
        )).single;
        expect(draft.clientSubmissionId, 'v9-report');
        expect(draft.businessAddress, 'Keep this typed address');
        expect(draft.notes, 'Keep these notes');
        expect(draft.lat, 13.960630);
        expect(draft.lng, 121.113447);
        expect(draft.locationMethod, YellowFlagLocationMethod.savedReport);
      } finally {
        await upgraded.close();
      }
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
