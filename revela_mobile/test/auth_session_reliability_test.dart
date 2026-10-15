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

const _apiBase = 'https://api.test.invalid';
const _syntheticToken = 'synthetic-test-token-only';

class _Reply {
  const _Reply(this.statusCode, this.body);

  final int statusCode;
  final Map<String, dynamic> body;
}

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({
    this.replies = const {},
    bool failWithTimeout = false,
    DioExceptionType? failureType,
  }) : failureType =
           failureType ??
           (failWithTimeout ? DioExceptionType.connectionTimeout : null);

  final Map<String, _Reply> replies;
  final DioExceptionType? failureType;
  final List<RequestOptions> requests = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (failureType != null) {
      throw DioException(
        requestOptions: options,
        type: failureType!,
        error: failureType == DioExceptionType.connectionError
            ? const SocketException('Failed host lookup')
            : null,
      );
    }
    final reply = replies[options.uri.path] ?? const _Reply(200, {'ok': true});
    return ResponseBody.fromString(
      jsonEncode(reply.body),
      reply.statusCode,
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
    Map<String, _Reply> replies = const {},
    bool failWithTimeout = false,
    DioExceptionType? failureType,
    String? initialToken = _syntheticToken,
    Map<String, dynamic>? currentUser = const {'id': 'local-test-user'},
  }) {
    if (initialToken != null) secureValues['jwt_token'] = initialToken;
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      secureValues,
    );
    adapter = _FakeAdapter(
      replies: replies,
      failWithTimeout: failWithTimeout,
      failureType: failureType,
    );
    service = AuthService.forTesting(
      dio: Dio(BaseOptions(baseUrl: _apiBase))..httpClientAdapter = adapter,
      apiBase: _apiBase,
      tokenReader: () async => secureValues['jwt_token'],
      clearSession: () async {
        clearSessionCount++;
        secureValues.remove('jwt_token');
        secureValues.remove('temp_2fa_token');
        secureValues.remove('must_change_password');
      },
      purgeAccount: () async {
        purgeAccountCount++;
        secureValues.clear();
      },
      clearLogoutSession: () async {
        clearLogoutSessionCount++;
        secureValues.remove('jwt_token');
        secureValues.remove('temp_2fa_token');
        secureValues.remove('must_change_password');
        secureValues.remove('authenticated_user_id');
      },
      currentUser: currentUser,
    );
  }

  late final _FakeAdapter adapter;
  late final AuthService service;
  final Map<String, String> secureValues = {};
  int clearSessionCount = 0;
  int purgeAccountCount = 0;
  int clearLogoutSessionCount = 0;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'saved session restores the server-validated inspector profile',
    () async {
      final harness = _Harness(
        currentUser: null,
        replies: {
          '/api/auth/me': const _Reply(200, {
            'userID': 41,
            'fullName': 'Offline Test Inspector',
            'email': 'inspector@example.invalid',
            'phone': '555-0100',
            'role': 'Inspector',
            'mustChangePassword': false,
          }),
        },
      );
      addTearDown(harness.service.dispose);

      final result = await harness.service.restoreSavedSession();

      expect(result, SessionRestoreResult.restored);
      expect(harness.service.currentUser?['id'], '41');
      expect(harness.service.currentUser?['role'], 'Inspector');
      expect(
        harness.service.currentUser?['fullName'],
        'Offline Test Inspector',
      );
      expect(
        harness.adapter.requests.single.headers['Authorization'],
        'Bearer $_syntheticToken',
      );
      expect(harness.secureValues['authenticated_user_id'], '41');
    },
  );

  test('no saved token skips session validation', () async {
    final harness = _Harness(initialToken: null, currentUser: null);
    addTearDown(harness.service.dispose);

    final result = await harness.service.restoreSavedSession();

    expect(result, SessionRestoreResult.noSavedSession);
    expect(harness.adapter.requests, isEmpty);
    expect(harness.service.isAuthenticated, isFalse);
  });

  test(
    'expired saved session clears only auth state and preserves drafts',
    () async {
      final harness = _Harness(
        currentUser: null,
        replies: {
          '/api/auth/me': const _Reply(401, {
            'error': 'Unauthorized',
            'message': 'This session ended.',
          }),
        },
      );
      harness.secureValues['inspection_draft_7'] = 'preserve-me';
      addTearDown(harness.service.dispose);

      final result = await harness.service.restoreSavedSession();

      expect(result, SessionRestoreResult.invalidSession);
      expect(harness.secureValues.containsKey('jwt_token'), isFalse);
      expect(harness.secureValues['inspection_draft_7'], 'preserve-me');
      expect(harness.clearSessionCount, 1);
      expect(harness.purgeAccountCount, 0);
    },
  );

  test('temporary server failure preserves token and offline drafts', () async {
    final harness = _Harness(
      currentUser: null,
      replies: {
        '/api/auth/me': const _Reply(503, {'error': 'Temporarily unavailable'}),
      },
    );
    harness.secureValues['inspection_draft_7'] = 'preserve-me';
    addTearDown(harness.service.dispose);

    final result = await harness.service.restoreSavedSession();

    expect(result, SessionRestoreResult.temporarilyUnavailable);
    expect(harness.secureValues['jwt_token'], _syntheticToken);
    expect(harness.secureValues['inspection_draft_7'], 'preserve-me');
    expect(harness.service.isAuthenticated, isFalse);
    expect(harness.clearSessionCount, 0);
    expect(harness.purgeAccountCount, 0);
  });

  test('connection timeout preserves the saved token for retry', () async {
    final harness = _Harness(currentUser: null, failWithTimeout: true);
    addTearDown(harness.service.dispose);

    final result = await harness.service.restoreSavedSession();

    expect(result, SessionRestoreResult.temporarilyUnavailable);
    expect(harness.secureValues['jwt_token'], _syntheticToken);
    expect(harness.service.isAuthenticated, isFalse);
    expect(harness.clearSessionCount, 0);
  });

  test(
    'password-change-required session does not open the dashboard',
    () async {
      final harness = _Harness(
        currentUser: null,
        replies: {
          '/api/auth/me': const _Reply(200, {
            'userID': 41,
            'fullName': 'Offline Test Inspector',
            'role': 'Inspector',
            'mustChangePassword': true,
          }),
        },
      );
      addTearDown(harness.service.dispose);

      final result = await harness.service.restoreSavedSession();

      expect(result, SessionRestoreResult.passwordChangeRequired);
      expect(harness.service.isAuthenticated, isFalse);
      expect(harness.secureValues['jwt_token'], _syntheticToken);
    },
  );
  test('authenticated API request uses Bearer access token', () async {
    final harness = _Harness();
    addTearDown(harness.service.dispose);

    await harness.service.dio.get('/api/auth/me');

    expect(
      harness.adapter.requests.single.headers['Authorization'],
      'Bearer $_syntheticToken',
    );
    expect(harness.purgeAccountCount, 0);
  });

  test(
    'public login endpoint does not receive a stored access token',
    () async {
      final harness = _Harness();
      addTearDown(harness.service.dispose);

      await harness.service.dio.post('/api/auth/login');

      expect(
        harness.adapter.requests.single.headers.containsKey('Authorization'),
        isFalse,
      );
    },
  );

  test('successful mocked login stores and uses its access token', () async {
    final harness = _Harness(
      initialToken: null,
      replies: {
        '/api/auth/login': const _Reply(200, {
          'access_token': _syntheticToken,
          'user': {
            'userID': 41,
            'fullName': 'Offline Test Inspector',
            'userRole': 'Inspector',
            'mustChangePassword': false,
          },
        }),
      },
    );
    addTearDown(harness.service.dispose);

    final result = await harness.service.loginWithRole(
      'inspector@example.invalid',
      'not-a-real-password',
    );
    await harness.service.dio.get('/api/auth/me');

    expect(result, LoginResult.success);
    expect(harness.service.isAuthenticated, isTrue);
    final storedToken = harness.secureValues['jwt_token'];
    expect(
      harness.adapter.requests
          .firstWhere((request) => request.uri.path == '/api/auth/me')
          .headers['Authorization'],
      'Bearer $storedToken',
    );
    expect(harness.purgeAccountCount, 0);
  });

  test('invalid credentials stay distinct from network failures', () async {
    final harness = _Harness(
      replies: {
        '/api/auth/login': const _Reply(401, {
          'error': 'Invalid email or password',
        }),
      },
    );
    addTearDown(harness.service.dispose);

    final result = await harness.service.loginWithRole(
      'inspector@example.invalid',
      'not-a-real-password',
    );

    expect(result, LoginResult.failed);
    expect(harness.service.lastAuthError, 'Invalid email or password.');
    expect(
      harness.adapter.requests.single.headers.containsKey('Authorization'),
      isFalse,
    );
    expect(harness.service.isAuthenticated, isTrue);
    expect(harness.purgeAccountCount, 0);
  });

  test(
    'active-session conflict gets a separate neutral login message',
    () async {
      const serverMessage =
          'This account is already signed in on a mobile device. Sign out on '
          'that device before signing in here.';
      final harness = _Harness(
        replies: {
          '/api/auth/login': const _Reply(409, {
            'code': 'account_in_use',
            'message': serverMessage,
          }),
        },
      );
      addTearDown(harness.service.dispose);

      final result = await harness.service.loginWithRole(
        'inspector@example.invalid',
        'not-a-real-password',
      );

      expect(result, LoginResult.activeSessionConflict);
      expect(
        harness.service.lastAuthError,
        'This account already has an active mobile session.',
      );
      expect(harness.service.isAuthenticated, isTrue);
      expect(harness.purgeAccountCount, 0);
    },
  );

  test('backend-confirmed disabled login account is purged', () async {
    final harness = _Harness(
      replies: {
        '/api/auth/login': const _Reply(401, {
          'error': 'Account is disabled. Please contact the administrator.',
        }),
      },
    );
    addTearDown(harness.service.dispose);

    final result = await harness.service.loginWithRole(
      'inspector@example.invalid',
      'not-a-real-password',
    );

    expect(result, LoginResult.accountRevoked);
    expect(harness.service.isAccountRevoked, isTrue);
    expect(harness.purgeAccountCount, 1);
  });

  test('access token is not sent to an unrelated host', () async {
    final harness = _Harness();
    addTearDown(harness.service.dispose);

    await harness.service.dio.get('https://untrusted.test.invalid/api/data');

    expect(
      harness.adapter.requests.single.headers.containsKey('Authorization'),
      isFalse,
    );
  });

  test('generic 404 does not purge or clear the session', () async {
    final harness = _Harness(
      replies: {
        '/api/missing': const _Reply(404, {'error': 'Not found'}),
      },
    );
    addTearDown(harness.service.dispose);

    await expectLater(
      harness.service.dio.get('/api/missing'),
      throwsA(isA<DioException>()),
    );

    expect(harness.service.isAuthenticated, isTrue);
    expect(harness.purgeAccountCount, 0);
    expect(harness.clearSessionCount, 0);
  });

  test('permission-denied 403 does not purge or revoke the session', () async {
    final harness = _Harness(
      replies: {
        '/api/forbidden': const _Reply(403, {
          'error': 'Forbidden',
          'message': 'Insufficient permissions.',
        }),
      },
    );
    addTearDown(harness.service.dispose);

    await expectLater(
      harness.service.dio.get('/api/forbidden'),
      throwsA(isA<DioException>()),
    );

    expect(harness.service.isAuthenticated, isTrue);
    expect(harness.service.isAccountRevoked, isFalse);
    expect(harness.purgeAccountCount, 0);
    expect(harness.clearSessionCount, 0);
  });

  test(
    'invalid or ended 401 clears active session but preserves account',
    () async {
      final harness = _Harness(
        replies: {
          '/api/protected': const _Reply(401, {
            'error': 'Unauthorized',
            'message': 'This session ended.',
          }),
        },
      );
      addTearDown(harness.service.dispose);

      await expectLater(
        harness.service.dio.get('/api/protected'),
        throwsA(isA<DioException>()),
      );

      expect(harness.service.isAuthenticated, isFalse);
      expect(harness.service.isAccountRevoked, isFalse);
      expect(harness.service.lastAuthError, contains('sign in again'));
      expect(harness.clearSessionCount, 1);
      expect(harness.purgeAccountCount, 0);
    },
  );

  test('backend-confirmed deactivation purges account state', () async {
    final harness = _Harness(
      replies: {
        '/api/protected': const _Reply(401, {
          'error': 'Unauthorized',
          'message': 'Account has been deactivated or removed.',
        }),
      },
    );
    addTearDown(harness.service.dispose);

    await expectLater(
      harness.service.dio.get('/api/protected'),
      throwsA(isA<DioException>()),
    );

    expect(harness.service.isAuthenticated, isFalse);
    expect(harness.service.isAccountRevoked, isTrue);
    expect(harness.purgeAccountCount, 1);
    expect(harness.clearSessionCount, 0);
  });

  test('connection timeout preserves the active session', () async {
    final harness = _Harness(failWithTimeout: true);
    addTearDown(harness.service.dispose);

    await expectLater(
      harness.service.dio.get('/api/protected'),
      throwsA(isA<DioException>()),
    );

    expect(harness.service.isAuthenticated, isTrue);
    expect(harness.purgeAccountCount, 0);
    expect(harness.clearSessionCount, 0);
  });

  test('DNS/connection failure preserves the active session', () async {
    final harness = _Harness(failureType: DioExceptionType.connectionError);
    addTearDown(harness.service.dispose);

    await expectLater(
      harness.service.dio.get('/api/protected'),
      throwsA(isA<DioException>()),
    );

    expect(harness.service.isAuthenticated, isTrue);
    expect(harness.purgeAccountCount, 0);
    expect(harness.clearSessionCount, 0);
  });

  test(
    'server error is shown as temporary and preserves the session',
    () async {
      final harness = _Harness(
        replies: {
          '/api/auth/login': const _Reply(503, {
            'error': 'Unable to start a secure session at this time.',
          }),
        },
      );
      addTearDown(harness.service.dispose);

      final result = await harness.service.loginWithRole(
        'inspector@example.invalid',
        'not-a-real-password',
      );

      expect(result, LoginResult.failed);
      expect(
        harness.service.lastAuthError,
        contains('temporarily unavailable'),
      );
      expect(harness.service.isAuthenticated, isTrue);
      expect(harness.purgeAccountCount, 0);
      expect(harness.clearSessionCount, 0);
    },
  );

  test('explicit logout uses the session-only cleanup path', () async {
    final harness = _Harness();
    addTearDown(harness.service.dispose);
    harness.secureValues['user_profile_41'] = 'cached-profile';
    harness.secureValues['saved_email'] = 'inspector@example.invalid';
    await harness.service.logout();

    expect(harness.clearLogoutSessionCount, 1);
    expect(harness.service.isAuthenticated, isFalse);
    expect(harness.purgeAccountCount, 0);
    expect(harness.secureValues.containsKey('jwt_token'), isFalse);
    expect(harness.secureValues['user_profile_41'], 'cached-profile');
    expect(harness.secureValues['saved_email'], 'inspector@example.invalid');
  });

  test(
    'HTTP 503 profile failure does not purge a valid local session',
    () async {
      final harness = _Harness(
        replies: {
          '/api/auth/me': const _Reply(503, {
            'error': 'Service temporarily unavailable',
          }),
        },
      );
      addTearDown(harness.service.dispose);

      final profile = await harness.service.getProfile(
        useCachedOnFailure: false,
      );

      expect(profile, isNull);
      expect(harness.service.isAuthenticated, isTrue);
      expect(harness.purgeAccountCount, 0);
      expect(harness.clearSessionCount, 0);
    },
  );
}
