import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
// ignore: depend_on_referenced_packages
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/auth_service.dart';
import 'package:revela_mobile/widgets/genuine_activity_observer.dart';

const _apiBase = 'https://activity.test.invalid';

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({
    this.statusCodes = const {},
    this.responseBodies = const {},
    this.failure,
    this.responseGate,
  });

  final Map<String, int> statusCodes;
  final Map<String, Map<String, dynamic>> responseBodies;
  final DioExceptionType? failure;
  final Completer<void>? responseGate;
  final List<RequestOptions> requests = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (responseGate != null) await responseGate!.future;
    if (failure != null) {
      throw DioException(requestOptions: options, type: failure!);
    }
    final statusCode = statusCodes[options.uri.path] ?? 200;
    return ResponseBody.fromString(
      jsonEncode(
        responseBodies[options.uri.path] ?? {'message': 'This session ended.'},
      ),
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
  _Harness({
    Map<String, int> statusCodes = const {},
    Map<String, Map<String, dynamic>> responseBodies = const {},
    DioExceptionType? failure,
    Completer<void>? responseGate,
    Map<String, dynamic>? currentUser = const {'id': 'test-inspector'},
  }) {
    secureValues['jwt_token'] = 'synthetic-test-token';
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      secureValues,
    );
    adapter = _FakeAdapter(
      statusCodes: statusCodes,
      responseBodies: responseBodies,
      failure: failure,
      responseGate: responseGate,
    );
    auth = AuthService.forTesting(
      dio: Dio(BaseOptions(baseUrl: _apiBase))..httpClientAdapter = adapter,
      apiBase: _apiBase,
      tokenReader: () async => secureValues['jwt_token'],
      clearSession: () async {
        secureValues.remove('jwt_token');
      },
      purgeAccount: () async {
        secureValues.clear();
      },
      clearLogoutSession: () async {
        secureValues.remove('jwt_token');
      },
      currentUser: currentUser,
      monotonicClockForTesting: () => clockMs,
    );
  }

  final Map<String, String> secureValues = {};
  int clockMs = 0;
  late final _FakeAdapter adapter;
  late final AuthService auth;

  int get activityRequestCount => adapter.requests
      .where((request) => request.uri.path == '/api/auth/activity')
      .length;

  int get heartbeatRequestCount => adapter.requests
      .where((request) => request.uri.path == '/api/auth/heartbeat')
      .length;

  Future<void> close() async => auth.dispose();
}

Widget _app(_Harness harness, {VoidCallback? onPressed}) {
  return GenuineActivityObserver(
    authService: harness.auth,
    child: MaterialApp(
      home: Scaffold(
        body: Center(
          child: ElevatedButton(
            key: const ValueKey('user-action'),
            onPressed: onPressed ?? () {},
            child: const Text('Continue'),
          ),
        ),
      ),
    ),
  );
}

Future<void> _tapAction(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('user-action')));
  await tester.pump();
  await tester.idle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    TestWidgetsFlutterBinding.instance.handleAppLifecycleStateChanged(
      AppLifecycleState.resumed,
    );
  });

  testWidgets('authenticated foreground input reports activity', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await _tapAction(tester);

    expect(harness.activityRequestCount, 1);
    expect(
      harness.adapter.requests.any(
        (request) => request.uri.path == '/api/auth/activity',
      ),
      isTrue,
    );
  });

  testWidgets('rapid events are throttled to at most one request per minute', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await _tapAction(tester);
    harness.clockMs = 59999;
    await _tapAction(tester);
    expect(harness.activityRequestCount, 1);

    harness.clockMs = 60000;
    await _tapAction(tester);
    expect(harness.activityRequestCount, 2);
  });

  testWidgets('idle foreground heartbeats do not count as user activity', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    harness.clockMs = const Duration(minutes: 20).inMilliseconds;
    await tester.pump(const Duration(minutes: 20));

    expect(harness.activityRequestCount, 0);
    expect(harness.heartbeatRequestCount, greaterThan(0));
  });

  testWidgets('background input and app-only events do not report activity', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));
    await tester.idle();
    final foregroundHeartbeatCount = harness.heartbeatRequestCount;

    TestWidgetsFlutterBinding.instance.handleAppLifecycleStateChanged(
      AppLifecycleState.paused,
    );
    await _tapAction(tester);
    harness.auth.notifyListeners();
    harness.clockMs = const Duration(minutes: 2).inMilliseconds;
    await tester.pump(const Duration(minutes: 2));
    expect(harness.activityRequestCount, 0);
    expect(harness.heartbeatRequestCount, foregroundHeartbeatCount);

    TestWidgetsFlutterBinding.instance.handleAppLifecycleStateChanged(
      AppLifecycleState.resumed,
    );
    await _tapAction(tester);
    expect(harness.activityRequestCount, 1);
    expect(harness.heartbeatRequestCount, foregroundHeartbeatCount + 1);
  });

  testWidgets('unauthenticated login screen does not report activity', (
    tester,
  ) async {
    final harness = _Harness(currentUser: null);
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await _tapAction(tester);

    expect(harness.activityRequestCount, 0);
  });

  testWidgets('successful login starts a fresh authenticated activity window', (
    tester,
  ) async {
    final harness = _Harness(
      currentUser: null,
      responseBodies: const {
        '/api/auth/login': {
          'access_token': 'fresh-synthetic-token',
          'user': {
            'userID': 41,
            'fullName': 'Test Inspector',
            'userRole': 'Inspector',
            'mustChangePassword': false,
          },
        },
      },
    );
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    final result = await tester.runAsync(
      () => harness.auth.loginWithRole(
        'inspector@example.invalid',
        'synthetic-test-password',
      ),
    );
    expect(result, LoginResult.success);
    expect(harness.auth.isAuthenticated, isTrue);

    await _tapAction(tester);
    expect(harness.activityRequestCount, 0);
    harness.clockMs = const Duration(minutes: 1).inMilliseconds;
    await _tapAction(tester);
    expect(harness.activityRequestCount, 1);
  });

  testWidgets('logout stops activity reporting immediately', (tester) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await tester.runAsync(harness.auth.logout);
    await _tapAction(tester);

    expect(harness.activityRequestCount, 0);
  });

  testWidgets('transient network failures do not block user actions or retry', (
    tester,
  ) async {
    var actionCount = 0;
    final harness = _Harness(failure: DioExceptionType.connectionError);
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness, onPressed: () => actionCount++));

    await _tapAction(tester);

    expect(actionCount, 1);
    expect(harness.activityRequestCount, 1);
    expect(harness.auth.isAuthenticated, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    '401 invalidates the session and subsequent input cannot revive it',
    (tester) async {
      final harness = _Harness(statusCodes: const {'/api/auth/activity': 401});
      addTearDown(harness.close);
      await tester.pumpWidget(_app(harness));

      await _tapAction(tester);
      await tester.pump();
      expect(harness.auth.isAuthenticated, isFalse);

      await _tapAction(tester);
      expect(harness.activityRequestCount, 1);
    },
  );

  testWidgets('403 activity response preserves existing auth semantics', (
    tester,
  ) async {
    final harness = _Harness(statusCodes: const {'/api/auth/activity': 403});
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await _tapAction(tester);

    expect(harness.activityRequestCount, 1);
    expect(harness.auth.isAuthenticated, isTrue);
    expect(harness.auth.isAccountRevoked, isFalse);
  });

  testWidgets('reauthenticated saved session starts a fresh activity window', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await _tapAction(tester);
    expect(harness.activityRequestCount, 1);
    await tester.runAsync(harness.auth.logout);

    harness.secureValues.addAll({
      'jwt_token': 'fresh-synthetic-token',
      'last_active_user_id': 'test-inspector',
      'user_fullName': 'Test Inspector',
      'user_role': 'Inspector',
    });
    await harness.auth.activateSavedUserSession();
    await _tapAction(tester);

    expect(harness.activityRequestCount, 2);
  });

  testWidgets('in-flight activity requests are never overlapped', (
    tester,
  ) async {
    final responseGate = Completer<void>();
    final harness = _Harness(responseGate: responseGate);
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await tester.tap(find.byKey(const ValueKey('user-action')));
    await tester.pump();
    await tester.idle();
    harness.clockMs = const Duration(minutes: 1).inMilliseconds;
    await _tapAction(tester);

    expect(harness.activityRequestCount, 1);
    responseGate.complete();
    await tester.idle();
  });

  testWidgets('foreground hardware key input is treated as genuine activity', (
    tester,
  ) async {
    final harness = _Harness();
    addTearDown(harness.close);
    await tester.pumpWidget(_app(harness));

    await tester.sendKeyEvent(LogicalKeyboardKey.keyA);
    await tester.pump();
    await tester.idle();

    expect(harness.activityRequestCount, 1);
  });
}
