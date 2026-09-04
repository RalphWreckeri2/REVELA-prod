import 'dart:async';
import 'package:dio/dio.dart';
import 'dart:convert';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../pages/login_page.dart';
import 'api_config.dart';

enum LoginResult {
  success,
  mustChangePassword,
  twoFactorRequired,
  notInspector,
  accountRevoked,
  failed,
  networkError,
  canceled,
}

class AuthService extends ChangeNotifier {
  late final Dio _dio;
  Map<String, dynamic>? _currentUser;

  Dio get dio => _dio;
  Map<String, dynamic>? get currentUser => _currentUser;
  bool get isAuthenticated => _currentUser != null;

  static String get apiBase => ApiConfig.apiBase;

  final FlutterSecureStorage _storage = const FlutterSecureStorage();
  final LocalAuthentication _localAuth = LocalAuthentication();
  StreamSubscription<String>? _fcmTokenRefreshSubscription;

  static final GlobalKey<NavigatorState> navigatorKey =
      GlobalKey<NavigatorState>();

  static final AuthService _instance = AuthService._internal();

  factory AuthService() {
    return _instance;
  }

  AuthService._internal() {
    _dio = Dio(
      BaseOptions(
        baseUrl: ApiConfig.apiBase,
        headers: {'Content-Type': 'application/json'},
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
      ),
    );

    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest:
            (RequestOptions options, RequestInterceptorHandler handler) async {
              options.baseUrl = ApiConfig.apiBase;
              try {
                final token = await _storage.read(key: 'jwt_token');
                if (token != null) {
                  options.headers['Authorization'] = 'Bearer $token';
                }
              } catch (e) {
                debugPrint('AuthService interceptor token read error: $e');
              }
              return handler.next(options);
            },
        onError: (DioException e, ErrorInterceptorHandler handler) async {
          // Force-logout & purge storage on 401/403 for authenticated endpoints.
          final path = e.requestOptions.path;
          final isAuthEndpoint =
              path.contains('/auth/login') ||
              path.contains('/auth/logout') ||
              path.contains('/auth/request-manual-reset') ||
              path.contains('/auth/request-otp') ||
              path.contains('/auth/reset-password');

          final statusCode = e.response?.statusCode;
          if ((statusCode == 401 || statusCode == 403 || statusCode == 404) && !isAuthEndpoint) {
            await purgeRevokedAccountState(
              reason: 'Your inspector account access has been revoked by an administrator.',
            );
            if (navigatorKey.currentState != null) {
              navigatorKey.currentState!.pushAndRemoveUntil(
                MaterialPageRoute(
                  builder: (_) => const LoginPage(accountRevokedNotice: true),
                ),
                (route) => false,
              );
            }
          }
          return handler.next(e);
        },
      ),
    );
  }

  void syncBaseUrl() {
    _dio.options.baseUrl = ApiConfig.apiBase;
  }

  String? _lastAuthError;
  String? get lastAuthError => _lastAuthError;

  Future<LoginResult> loginWithRole(String email, String password) async {
    _lastAuthError = null;
    final reachable = await ApiConfig.ensureReachable();
    if (reachable == null) {
      _lastAuthError =
          'Cannot connect to server at ${ApiConfig.apiBase}. Please verify the backend is running.';
      return LoginResult.networkError;
    }
    syncBaseUrl();

    try {
      final response = await _dio.post(
        '/api/auth/login',
        data: {'email': email, 'password': password, 'source': 'mobile'},
      );

      if (response.statusCode == 200) {
        if (response.data['status'] == '2fa_required') {
          await _storage.write(
            key: 'temp_2fa_token',
            value: response.data['tempToken'],
          );
          await _storage.write(key: 'temp_email', value: email);
          await _storage.write(key: 'temp_password', value: password);
          return LoginResult.twoFactorRequired;
        }

        if (response.data['access_token'] != null) {
          final user = response.data['user'];

          final String userRole =
              user?['userRole']?.toString() ?? user?['role']?.toString() ?? '';
          if (userRole.trim().toLowerCase() != 'inspector') {
            _lastAuthError =
                'Access denied. Account has role "$userRole", but only Inspectors can use the mobile app.';
            return LoginResult.notInspector;
          }

          final String token = response.data['access_token'];
          await _storage.write(key: 'jwt_token', value: token);
          await _registerFcmToken();

          // Save credentials securely for biometric re-login
          await _storage.write(key: 'saved_email', value: email);
          await _storage.write(key: 'saved_password', value: password);

          bool mustChange = false;
          if (user != null && user is Map) {
            // Persist per-user profile under a user-scoped key so offline restore
            // and multi-user flows won't collide.
            final String userId =
                (user['userID'] ?? user['userId'] ?? user['id'] ?? '')
                    .toString();

            await _storage.write(
              key: 'user_fullName',
              value: user['fullName']?.toString() ?? '',
            );
            await _storage.write(key: 'user_role', value: userRole);
            mustChange = user['mustChangePassword'] == true;
            await _storage.write(
              key: 'must_change_password',
              value: mustChange ? 'true' : 'false',
            );

            // Cache the full user object (including token) under a user-scoped key.
            if (userId.isNotEmpty) {
              await _cacheUserProfile(
                userId,
                fullName: user['fullName']?.toString() ?? '',
                role: userRole,
                token: token,
                email: email,
                phone: user['phone']?.toString(),
              );
              await _persistAuthenticatedUserState(
                userId,
                user['fullName']?.toString() ?? '',
                userRole,
                phone: user['phone']?.toString(),
              );
              if (user['phone'] != null &&
                  user['phone'].toString().isNotEmpty) {
                await _storage.write(
                  key: 'user_phone',
                  value: user['phone'].toString(),
                );
              }
              if (!mustChange) {
                _currentUser = {
                  'id': userId,
                  'fullName': user['fullName']?.toString() ?? '',
                  'role': userRole,
                  'token': token,
                  'email': email,
                  'phone': user['phone']?.toString() ?? '',
                };
                notifyListeners();
              }
              // Sync FCM token immediately on successful login
              unawaited(_registerFcmToken());
            }
          }

          if (mustChange) {
            return LoginResult.mustChangePassword;
          }

          return LoginResult.success;
        }
      }
      _lastAuthError =
          response.data?['error']?.toString() ?? 'Invalid email or password.';
      return LoginResult.failed;
    } on DioException catch (e) {
      if (e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout) {
        _lastAuthError =
            'Connection timed out or failed to reach ${ApiConfig.apiBase}.';
        return LoginResult.networkError;
      }

      final errorMsg =
          e.response?.data?['error']?.toString() ??
          e.response?.data?['message']?.toString() ??
          '';
      _lastAuthError = errorMsg.isNotEmpty
          ? errorMsg
          : (e.message ?? 'Authentication failed');

      if (e.response?.statusCode == 403) {
        if (errorMsg.toLowerCase().contains('inspector')) {
          return LoginResult.notInspector;
        }
      }

      debugPrint(
        'Login Error (${e.response?.statusCode}): ${e.response?.data ?? e.message}',
      );
      return LoginResult.failed;
    }
  }

  Future<bool> requestManualPasswordReset(String email) async {
    try {
      final response = await _dio.post(
        '/api/auth/request-manual-reset',
        data: {'email': email},
      );
      // Clear saved password so biometrics is disabled until they login again with new password
      await _storage.delete(key: 'saved_password');
      return response.statusCode == 200;
    } catch (e) {
      debugPrint('Reset Request Error: $e');
      return false; // Still return false on catastrophic error, but API returns 200 even if not found
    }
  }

  Future<LoginResult> verify2FALogin(String code) async {
    try {
      final tempToken = await _storage.read(key: 'temp_2fa_token');
      if (tempToken == null) return LoginResult.failed;

      final response = await _dio.post(
        '/api/auth/verify-2fa-login',
        options: Options(headers: {'Authorization': 'Bearer $tempToken'}),
        data: {'code': code},
      );

      if (response.statusCode == 200 && response.data['access_token'] != null) {
        final String token = response.data['access_token'];
        await _storage.write(key: 'jwt_token', value: token);
        await _storage.delete(key: 'temp_2fa_token');
        await _registerFcmToken();

        final profile = await getProfile();
        if (profile != null) {
          final String userRole =
              profile['role']?.toString() ??
              profile['userRole']?.toString() ??
              '';
          if (userRole != 'Inspector') {
            return LoginResult.notInspector;
          }

          // Persist profile locally, user-scoped
          final String userId =
              (profile['userID'] ?? profile['userId'] ?? profile['id'] ?? '')
                  .toString();
          await _storage.write(
            key: 'user_fullName',
            value: profile['fullName']?.toString() ?? '',
          );
          await _storage.write(key: 'user_role', value: userRole);

          try {
            if (userId.isNotEmpty) {
              await _cacheUserProfile(
                userId,
                fullName: profile['fullName']?.toString() ?? '',
                role: userRole,
                token: token,
                email: profile['email']?.toString(),
                phone: profile['phone']?.toString(),
              );
              await _persistAuthenticatedUserState(
                userId,
                profile['fullName']?.toString() ?? '',
                userRole,
                phone: profile['phone']?.toString(),
              );
              if (profile['phone'] != null &&
                  profile['phone'].toString().isNotEmpty) {
                await _storage.write(
                  key: 'user_phone',
                  value: profile['phone'].toString(),
                );
              }
              // Sync FCM token after 2FA login
              unawaited(_registerFcmToken());
            }
            // Do not notifyListeners inside dialog flow; caller will pop dialog and activate session
          } catch (e) {
            debugPrint('Failed to cache profile after 2FA: $e');
          }

          if (profile['mustChangePassword'] == true) {
            return LoginResult.mustChangePassword;
          }
        }
        return LoginResult.success;
      }
      return LoginResult.failed;
    } on DioException catch (e) {
      debugPrint(
        '2FA Login Verification error: ${e.response?.data ?? e.message}',
      );
      return LoginResult.failed;
    }
  }

  Future<void> activateSavedUserSession({bool notify = true}) async {
    final userId = await _storage.read(key: 'last_active_user_id') ?? '';
    final fullName = await _storage.read(key: 'user_fullName') ?? '';
    final userRole = await _storage.read(key: 'user_role') ?? 'Inspector';
    final token = await _storage.read(key: 'jwt_token') ?? '';
    _currentUser = {
      'id': userId,
      'fullName': fullName,
      'role': userRole,
      'token': token,
    };
    if (notify) notifyListeners();
  }

  Future<Map<String, dynamic>> changePassword(
    String oldPassword,
    String newPassword,
  ) async {
    try {
      final response = await _dio.put(
        '/api/auth/change-password',
        data: {'oldPassword': oldPassword, 'newPassword': newPassword},
      );
      if (response.statusCode == 200) {
        await _storage.write(key: 'must_change_password', value: 'false');

        // Update the saved password so biometrics doesn't break
        final email = await _storage.read(key: 'saved_email');
        if (email != null) {
          await _storage.write(key: 'saved_password', value: newPassword);
        }

        return {
          'success': true,
          'message':
              response.data['message'] ?? 'Password changed successfully',
        };
      }
      return {
        'success': false,
        'error': response.data['error'] ?? 'Failed to change password',
      };
    } on DioException catch (e) {
      final err =
          e.response?.data?['error'] ?? e.message ?? 'An error occurred';
      return {'success': false, 'error': err};
    }
  }

  Future<Map<String, dynamic>?> getProfile() async {
    try {
      final response = await _dio.get('/api/auth/me');
      if (response.statusCode == 200 && response.data is Map) {
        final data = Map<String, dynamic>.from(response.data);
        if (data['fullName'] != null) {
          await _storage.write(
            key: 'user_fullName',
            value: data['fullName'].toString(),
          );
        }
        if (data['email'] != null) {
          await _storage.write(
            key: 'saved_email',
            value: data['email'].toString(),
          );
        }
        if (data['phone'] != null) {
          await _storage.write(
            key: 'user_phone',
            value: data['phone'].toString(),
          );
        }
        return data;
      }
      return null;
    } catch (e) {
      debugPrint('Error getting profile: $e');
      if (e is DioException) {
        final code = e.response?.statusCode;
        if (code == 401 || code == 403 || code == 404) {
          await purgeRevokedAccountState(
            reason: 'You cannot access the application. The administrator has already removed or deactivated your account.',
          );
          return null;
        }
      }
      final fullName = await _storage.read(key: 'user_fullName');
      final email = await _storage.read(key: 'saved_email');
      final phone = await _storage.read(key: 'user_phone');
      if (fullName != null || email != null || phone != null) {
        return {
          'fullName': fullName ?? '',
          'email': email ?? '',
          'phone': phone ?? '',
        };
      }
      return null;
    }
  }

  Future<Map<String, dynamic>> updateProfile(
    String name,
    String email, [
    String? phone,
  ]) async {
    try {
      final data = {
        'fullName': name,
        'email': email,
        if (phone != null && phone.trim().isNotEmpty) 'phone': phone.trim(),
      };

      final response = await _dio.patch(
        '/api/auth/me',
        data: data,
        options: Options(
          sendTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 5),
        ),
      );
      if (response.statusCode == 200) {
        await _storage.write(key: 'user_fullName', value: name);
        await _storage.write(key: 'saved_email', value: email);
        if (phone != null && phone.trim().isNotEmpty) {
          await _storage.write(key: 'user_phone', value: phone.trim());
        }
        return {
          'success': true,
          'message': response.data['message'] ?? 'Profile updated successfully',
        };
      }
      return {
        'success': false,
        'error': response.data?['error'] ?? 'Failed to update profile',
      };
    } on DioException catch (e) {
      debugPrint(
        'updateProfile API failed or hung: ${e.message}. Mocking success.',
      );
      // Fallback: save locally
      await _storage.write(key: 'user_fullName', value: name);
      await _storage.write(key: 'saved_email', value: email);
      if (phone != null && phone.trim().isNotEmpty) {
        await _storage.write(key: 'user_phone', value: phone.trim());
      }
      return {'success': true, 'message': 'Profile updated locally'};
    }
  }

  // ----- Local profile helpers for offline-first, account-scoped storage -----
  String _profileKey(String userId) => 'user_profile_$userId';

  Future<Map<String, dynamic>?> getCachedUserProfile(String userId) async {
    if (userId.isEmpty) return null;
    final raw = await _storage.read(key: _profileKey(userId));
    if (raw == null) return null;
    try {
      if (raw.trim().startsWith('{')) {
        try {
          return Map<String, dynamic>.from(jsonDecode(raw));
        } catch (e) {
          debugPrint('Cached profile JSON decode failed for $userId: $e');
        }
      }

      // Fallback: simple parsing of legacy `'{key: value, ...}'` strings.
      final cleaned = raw
          .trim()
          .replaceAll(RegExp(r'^[{]'), '')
          .replaceAll(RegExp(r'[}]$'), '');
      final parts = cleaned.split(',');
      final m = <String, dynamic>{};
      for (var p in parts) {
        final idx = p.indexOf(':');
        if (idx <= 0) continue;
        final k = p
            .substring(0, idx)
            .trim()
            .replaceAll("'", '')
            .replaceAll('"', '');
        var v = p.substring(idx + 1).trim();
        v = v.replaceAll("'", '');
        v = v.replaceAll('"', '');
        m[k] = v;
      }
      return m;
    } catch (e) {
      debugPrint('Failed to parse cached profile: $e');
      return null;
    }
  }

  /// Returns the currently authenticated user id persisted in secure storage (if any).
  Future<String?> getAuthenticatedUserId() async {
    return await _storage.read(key: 'authenticated_user_id');
  }

  /// Returns the cached profile associated with the active biometric credential (if any).
  Future<Map<String, dynamic>?> getActiveBiometricProfile() async {
    final uid = await _storage.read(key: 'active_biometric_user_id');
    if (uid != null && uid.isNotEmpty) {
      final profile = await getCachedUserProfile(uid);
      if (profile != null) return profile;
    }

    final profiles = await listCachedProfiles();
    if (profiles.isNotEmpty) {
      debugPrint(
        'getActiveBiometricProfile: no active biometric user id; falling back to first cached profile',
      );
      return profiles.first;
    }
    return null;
  }

  /// Lists all locally cached user profiles (keys starting with `user_profile_`).
  Future<List<Map<String, dynamic>>> listCachedProfiles() async {
    final all = await _storage.readAll();
    final profiles = <Map<String, dynamic>>[];
    for (final entry in all.entries) {
      if (entry.key.startsWith('user_profile_')) {
        final id = entry.key.substring('user_profile_'.length);
        final p = await getCachedUserProfile(id);
        if (p != null) profiles.add(p);
      }
    }
    return profiles;
  }

  /// Verifies a stored PIN for a given user id. PINs must be previously saved
  /// under key `user_pin_<userId>`. Returns true when PIN matches stored value.
  Future<bool> verifyPin(String userId, String pin) async {
    if (userId.isEmpty) return false;
    final key = 'user_pin_\$userId';
    final stored = await _storage.read(key: key);
    if (stored == null) return false;
    return stored == pin;
  }

  /// Hydrate local runtime storage for [userId] using cached profile data.
  /// Returns true if hydration succeeded (profile found and values written).
  Future<bool> hydrateLocalSessionForUserId(String userId) async {
    if (userId.isEmpty) return false;
    final profile = await getCachedUserProfile(userId);
    if (profile == null) return false;
    try {
      await _storage.write(
        key: 'user_fullName',
        value: profile['fullName']?.toString() ?? '',
      );
      await _storage.write(
        key: 'user_role',
        value: profile['role']?.toString() ?? '',
      );
      await _storage.write(key: 'authenticated_user_id', value: userId);
      await _storage.write(key: 'active_biometric_user_id', value: userId);
      // Also persist a last_logged_in_user_id to help fallback restores
      await _storage.write(key: 'last_logged_in_user_id', value: userId);
      if (profile['phone'] != null &&
          profile['phone'].toString().isNotEmpty) {
        await _storage.write(
          key: 'user_phone',
          value: profile['phone'].toString(),
        );
      }
      if (profile['email'] != null &&
          profile['email'].toString().isNotEmpty) {
        await _storage.write(
          key: 'saved_email',
          value: profile['email'].toString(),
        );
      }
      _currentUser = profile;
      notifyListeners();
      debugPrint('hydrateLocalSessionForUserId: hydrated user $userId');
      if (profile.containsKey('token') &&
          (profile['token']?.toString().isNotEmpty ?? false)) {
        await _storage.write(
          key: 'jwt_token',
          value: profile['token']?.toString(),
        );
      }
      // Register/sync FCM token in background if network is available
      unawaited(_registerFcmToken());
      return true;
    } catch (e) {
      debugPrint('hydrateLocalSessionForUserId failed: $e');
      return false;
    }
  }

  /// Restores an account-scoped offline session using cached biometric profile data.
  /// Returns true when a user profile was successfully hydrated from local storage.
  Future<bool> restoreOfflineBiometricUser() async {
    try {
      String? activeUserId = await _storage.read(
        key: 'active_biometric_user_id',
      );
      if (activeUserId == null || activeUserId.isEmpty) {
        activeUserId =
            await _storage.read(key: 'authenticated_user_id') ??
            await _storage.read(key: 'last_logged_in_user_id');
        debugPrint(
          'restoreOfflineBiometricUser: active_biometric_user_id missing, fallback to $activeUserId',
        );
      }

      if (activeUserId != null && activeUserId.isNotEmpty) {
        final profile = await getCachedUserProfile(activeUserId);
        if (profile != null) {
          return await hydrateLocalSessionForUserId(activeUserId);
        }
      }

      final cachedProfiles = await listCachedProfiles();
      if (cachedProfiles.isNotEmpty) {
        final fallbackProfile = cachedProfiles.first;
        final fallbackUserId =
            (fallbackProfile['id'] ??
                    fallbackProfile['userID'] ??
                    fallbackProfile['userId'] ??
                    '')
                .toString();
        if (fallbackUserId.isNotEmpty) {
          debugPrint(
            'restoreOfflineBiometricUser: falling back to any cached profile id $fallbackUserId',
          );
          return await hydrateLocalSessionForUserId(fallbackUserId);
        }
      }

      debugPrint(
        'restoreOfflineBiometricUser: no cached profile found for offline restore',
      );
      return false;
    } catch (e) {
      debugPrint('Offline biometric restore failed: $e');
      return false;
    }
  }

  Future<bool> canUseBiometrics() async {
    try {
      return await _localAuth.canCheckBiometrics ||
          await _localAuth.isDeviceSupported();
    } catch (e) {
      return false;
    }
  }

  Future<bool> authenticateForSetup() async {
    try {
      final canCheck = await canUseBiometrics();
      if (!canCheck) return false;

      return await _localAuth.authenticate(
        localizedReason: 'Please authenticate to enable biometric login',
        persistAcrossBackgrounding: true,
        biometricOnly: false,
      );
    } catch (e) {
      debugPrint('Setup Biometric error: $e');
      return false;
    }
  }

  Future<bool> hasSavedCredentials() async {
    final email = await _storage.read(key: 'saved_email');
    final password = await _storage.read(key: 'saved_password');
    return email != null &&
        email.isNotEmpty &&
        password != null &&
        password.isNotEmpty;
  }

  Future<LoginResult> biometricLogin() async {
    try {
      final canCheck = await canUseBiometrics();
      if (!canCheck) return LoginResult.failed;

      final reachable = await ApiConfig.ensureReachable();
      final isOffline = reachable == null;
      final localizedReason = isOffline
          ? 'Authenticate to unlock your account (offline)'
          : 'Please authenticate to log in';

      final didAuthenticate = await _localAuth.authenticate(
        localizedReason: localizedReason,
        persistAcrossBackgrounding: true,
        biometricOnly: false,
      );

      if (!didAuthenticate) return LoginResult.canceled;

      if (isOffline) {
        final restored = await restoreOfflineBiometricUser();
        return restored ? LoginResult.success : LoginResult.networkError;
      }

      // When online, check server profile status to verify account is still active
      final onlineProfile = await getProfile();
      if (onlineProfile == null) {
        // Account has been disabled or removed on backend
        await purgeRevokedAccountState(
          reason: 'Your inspector account has been removed or deactivated by an administrator.',
        );
        return LoginResult.accountRevoked;
      }

      // When online and active, prefer local restore if a cached biometric profile exists.
      final activeUserId = await _storage.read(key: 'active_biometric_user_id');
      if (activeUserId != null && activeUserId.isNotEmpty) {
        final hydrated = await hydrateLocalSessionForUserId(activeUserId);
        if (hydrated) return LoginResult.success;
      }

      // No cached local profile available, continue with saved credentials.
      final email = await _storage.read(key: 'saved_email');
      final password = await _storage.read(key: 'saved_password');
      if (email == null || password == null) return LoginResult.failed;

      return await loginWithRole(email, password);
    } catch (e) {
      debugPrint('Biometric error: $e');
      return LoginResult.canceled;
    }
  }

  Future<Map<String, dynamic>?> setup2FA() async {
    try {
      final response = await _dio.post('/api/auth/setup-2fa');
      if (response.statusCode == 200) {
        return response.data;
      }
      return null;
    } on DioException catch (e) {
      debugPrint('Setup 2FA error: ${e.response?.data ?? e.message}');
      return null;
    }
  }

  Future<Map<String, dynamic>> verify2FASetup(String code) async {
    try {
      final response = await _dio.post(
        '/api/auth/verify-2fa-setup',
        data: {'code': code},
      );
      if (response.statusCode == 200) {
        return {'success': true, 'message': response.data['message']};
      }
      return {
        'success': false,
        'error': response.data['error'] ?? 'Invalid code',
      };
    } on DioException catch (e) {
      final err =
          e.response?.data?['error'] ?? e.message ?? 'Verification failed';
      return {'success': false, 'error': err};
    }
  }

  Future<bool> disable2FA() async {
    try {
      final response = await _dio.post('/api/auth/disable-2fa');
      return response.statusCode == 200;
    } catch (e) {
      debugPrint('Disable 2FA error: $e');
      return false;
    }
  }

  Future<bool> updateEmailAlerts(bool enabled) async {
    try {
      final response = await _dio.patch(
        '/api/auth/me/preferences',
        data: {'emailInspectionAlerts': enabled},
      );
      return response.statusCode == 200;
    } catch (e) {
      debugPrint('Update email alerts error: $e');
      return false;
    }
  }

  Future<bool> authenticateOfflineBiometric() async {
    final canCheck = await canUseBiometrics();
    if (!canCheck) return false;

    try {
      final didAuthenticate = await _localAuth.authenticate(
        localizedReason: 'Authenticate to unlock your account (offline)',
        persistAcrossBackgrounding: true,
        biometricOnly: false,
      );
      return didAuthenticate;
    } catch (e) {
      debugPrint('Offline biometric authentication failed: $e');
      return false;
    }
  }

  Future<void> _cacheUserProfile(
    String userId, {
    required String fullName,
    required String role,
    required String token,
    String? email,
    String? phone,
  }) async {
    final profile = {
      'id': userId,
      'fullName': fullName,
      'role': role,
      'token': token,
      if (email != null && email.isNotEmpty) 'email': email,
      if (phone != null && phone.isNotEmpty) 'phone': phone,
    };

    try {
      await _storage.write(
        key: _profileKey(userId),
        value: jsonEncode(profile),
      );
      debugPrint('CACHE SUCCESS: Saved profile for user: $userId');
    } catch (e) {
      debugPrint('CACHE FAILED: Could not save profile for user $userId: $e');
    }
  }

  Future<void> _persistAuthenticatedUserState(
    String userId,
    String fullName,
    String role, {
    String? phone,
  }) async {
    if (userId.isEmpty) return;
    await _storage.write(key: 'authenticated_user_id', value: userId);
    await _storage.write(key: 'active_biometric_user_id', value: userId);
    await _storage.write(key: 'user_fullName', value: fullName);
    await _storage.write(key: 'user_role', value: role);
    if (phone != null && phone.isNotEmpty) {
      await _storage.write(key: 'user_phone', value: phone);
    }
    await _storage.write(key: 'last_logged_in_user_id', value: userId);
  }

  /// Registers the token after login and whenever Firebase rotates it.
  /// This is intentionally never called for app lifecycle pauses/termination.
  Future<void> _registerFcmToken() async {
    try {
      final fcmToken = await FirebaseMessaging.instance.getToken();
      if (fcmToken == null || fcmToken.isEmpty) {
        debugPrint('[FCM TOKEN WARNING] Firebase returned no device token.');
        return;
      }

      await _dio.put('/api/auth/fcm-token', data: {'fcmToken': fcmToken});
      debugPrint(
        '[FCM TOKEN REGISTERED] Device token saved for this inspector.',
      );

      _fcmTokenRefreshSubscription ??= FirebaseMessaging.instance.onTokenRefresh
          .listen((refreshedToken) async {
            try {
              await _dio.put(
                '/api/auth/fcm-token',
                data: {'fcmToken': refreshedToken},
              );
              debugPrint(
                '[FCM TOKEN REGISTERED] Refreshed device token saved.',
              );
            } catch (e) {
              debugPrint('[FCM TOKEN ERROR] Refresh sync failed: $e');
            }
          });
    } catch (e) {
      // A token-sync failure must not prevent a valid inspector login.
      debugPrint('[FCM TOKEN ERROR] Registration failed: $e');
    }
  }

  /// Manually sync FCM token to backend
  Future<void> syncFcmToken() => _registerFcmToken();

  /// Clears only the saved password, typically after a biometric login fails.
  Future<void> clearSavedPassword() async {
    await _storage.delete(key: 'saved_password');
  }

  /// Immediately ends the active session WITHOUT contacting the server.
  ///
  /// Used when connectivity drops mid-session (the `/auth/logout` call would
  /// be unreachable anyway). Unlike [logout], this intentionally PRESERVES:
  ///  * `user_profile_<id>` entries → so offline biometric re-login works
  ///  * `saved_email` / `saved_password` → biometric eligibility
  ///  * `active_biometric_user_id` / `last_logged_in_user_id`
  /// while clearing everything session-scoped.
  Future<void> forceStopSession() async {
    try {
      await _storage.delete(key: 'jwt_token');
      await _storage.delete(key: 'temp_2fa_token');
      await _storage.delete(key: 'must_change_password');
    } catch (e) {
      debugPrint('forceStopSession: storage cleanup failed: $e');
    }

    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();
    _currentUser = null;
    notifyListeners(); // main.dart listener navigates to LoginPage
  }

  /// Completely wipes all local secure storage, cached profiles, tokens, and credentials.
  /// Used when an account is removed, revoked, or deactivated by an administrator.
  Future<void> purgeRevokedAccountState({String? reason}) async {
    try {
      await _storage.deleteAll();
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('biometric_enabled');
      await prefs.remove('onboarding_completed');
      await prefs.remove('cached_in_app_notifications_list');
    } catch (e) {
      debugPrint('Error purging secure storage: $e');
    }
    await _fcmTokenRefreshSubscription?.cancel();
    _fcmTokenRefreshSubscription = null;

    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();

    _currentUser = null;
    _lastAuthError = reason ??
        'You cannot access the application. The administrator has already removed or deactivated your account.';
    notifyListeners();
  }

  Future<void> logout() async {
    try {
      await _dio.post('/api/auth/logout');
    } catch (_) {}

    _lastAuthError = null;

    try {
      await _storage.delete(key: 'jwt_token');
      await _storage.delete(key: 'temp_2fa_token');
      await _storage.delete(key: 'must_change_password');
      await _storage.delete(key: 'authenticated_user_id');
    } catch (e) {
      debugPrint('Error clearing session tokens during logout: $e');
    }

    await _fcmTokenRefreshSubscription?.cancel();
    _fcmTokenRefreshSubscription = null;

    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();

    _currentUser = null;
    notifyListeners();

    navigatorKey.currentState?.pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => const LoginPage(accountRevokedNotice: false),
      ),
      (route) => false,
    );
  }
}
