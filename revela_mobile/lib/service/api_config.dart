import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'runtime_build_config.dart';

/// Resolves the Flask API base URL for emulator, USB (adb reverse), and Wi‑Fi.
class ApiConfig {
  static const String _prefKey = 'api_base_url';
  static const String _compileTimeBase = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'https://api.revelasys.site',
  );

  static const Duration _probeTimeout = Duration(seconds: 5);

  static String? _resolvedBase;
  static bool _isQa = false;
  static String? _qaEndpoint;
  static String? _qaConfigurationError;
  @visibleForTesting
  static Future<bool> Function(String base)? probeOverride;

  static bool get isQa => _isQa;
  static bool get isQaReady => !_isQa || _qaEndpoint != null;
  static String? get qaConfigurationError => _qaConfigurationError;

  static String get qaConnectionErrorMessage =>
      'Cannot reach the local QA backend. Check the configured local test '
      'endpoint and confirm the isolated backend is running.';

  /// Active API base URL. An unconfigured QA build uses a dead local URL;
  /// AuthService rejects requests before any connection can be attempted.
  static String get apiBase {
    if (_resolvedBase != null) return _resolvedBase!;
    if (_isQa) return _qaEndpoint ?? 'http://127.0.0.1:1';
    if (_compileTimeBase.trim().isNotEmpty) {
      return _normalize(_compileTimeBase);
    }
    return 'https://api.revelasys.site';
  }

  static Future<void> initialize() async {
    await RuntimeBuildConfig.initialize();
    if (RuntimeBuildConfig.isQa) {
      _initializeQa(RuntimeBuildConfig.qaApiBase);
      return;
    }

    _isQa = false;
    _qaEndpoint = null;
    _qaConfigurationError = null;
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_prefKey);
      if (saved != null && saved.isNotEmpty) {
        _resolvedBase = _normalize(saved);
      } else if (_compileTimeBase.trim().isNotEmpty) {
        _resolvedBase = _normalize(_compileTimeBase);
      }
    } catch (e) {
      debugPrint('ApiConfig SharedPreferences read error: $e');
    }

    _resolvedBase ??= 'https://api.revelasys.site';
  }

  static void _initializeQa(String? configuredEndpoint) {
    _isQa = true;
    _resolvedBase = null;
    final endpoint = configuredEndpoint?.trim() ?? '';
    if (endpoint.isEmpty) {
      _qaEndpoint = null;
      _qaConfigurationError =
          RuntimeBuildConfig.error ??
          'QA API endpoint is missing. Configure qaApiBase with a local '
              'test backend address.';
      return;
    }

    final normalized = _normalize(endpoint);
    if (!isAllowedQaEndpoint(normalized)) {
      _qaEndpoint = null;
      _qaConfigurationError =
          'QA API endpoint must be an explicitly configured local HTTP '
          'address.';
      return;
    }
    _qaEndpoint = normalized;
    _qaConfigurationError = null;
  }

  @visibleForTesting
  static Future<void> initializeForTesting({
    required bool qaMode,
    String? qaEndpoint,
  }) async {
    RuntimeBuildConfig.configureForTesting(qaMode: qaMode, apiBase: qaEndpoint);
    _resolvedBase = null;
    await initialize();
  }

  @visibleForTesting
  static void resetForTesting() {
    _resolvedBase = null;
    _isQa = false;
    _qaEndpoint = null;
    _qaConfigurationError = null;
    probeOverride = null;
    RuntimeBuildConfig.resetForTesting();
  }

  static bool isAllowedQaEndpoint(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        uri.scheme != 'http' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.query.isNotEmpty ||
        uri.fragment.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        !uri.hasPort ||
        uri.port < 1 ||
        uri.port > 65535) {
      return false;
    }

    final host = uri.host.toLowerCase();
    if (host == 'localhost' || host == '127.0.0.1' || host == '10.0.2.2') {
      return true;
    }
    final octets = host.split('.');
    if (octets.length != 4 ||
        octets.any(
          (octet) =>
              octet.isEmpty ||
              !RegExp(r'^\d+$').hasMatch(octet) ||
              int.parse(octet) > 255,
        )) {
      return false;
    }
    final first = int.parse(octets[0]);
    final second = int.parse(octets[1]);
    return first == 10 ||
        (first == 172 && second >= 16 && second <= 31) ||
        (first == 192 && second == 168);
  }

  static bool allowsRequestUri(Uri uri) {
    if (!_isQa) return true;
    final endpoint = _qaEndpoint;
    if (endpoint == null) return false;
    final base = Uri.parse(endpoint);
    return uri.scheme == base.scheme &&
        uri.host == base.host &&
        uri.port == base.port;
  }

  /// Tries known dev endpoints until one responds to `/api/health`.
  static Future<String?> discover() async {
    final candidates = await _candidateUrls();
    for (final candidate in candidates) {
      if (await _probe(candidate)) {
        await _persist(candidate);
        _resolvedBase = candidate;
        debugPrint('ApiConfig: using $candidate');
        return candidate;
      }
    }
    debugPrint('ApiConfig: no reachable backend in candidate list');
    return null;
  }

  /// Verifies reachability; runs [discover] if the current base is down.
  ///
  /// Login requests do not depend on this probe: the login endpoint itself
  /// supplies the authoritative response and is allowed to handle cold starts.
  static Future<String?> ensureReachable() async {
    if (_isQa && !isQaReady) return null;
    final current = apiBase;
    if (await _probe(current)) {
      return current;
    }
    return discover();
  }

  static Future<void> _persist(String base) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_prefKey, base);
    } catch (e) {
      debugPrint('ApiConfig _persist error: $e');
    }
  }

  static Future<List<String>> _candidateUrls() async {
    if (_isQa) return _qaEndpoint == null ? const [] : [_qaEndpoint!];

    final seen = <String>{};
    final ordered = <String>[];

    void add(String url) {
      final n = _normalize(url);
      if (seen.add(n)) ordered.add(n);
    }

    // 1. Explicit --dart-define=API_BASE passed at build/run time
    if (_compileTimeBase.trim().isNotEmpty) {
      add(_compileTimeBase);
    }

    // 2. Production endpoint
    add('https://api.revelasys.site');

    // 3. Previously verified working URL from SharedPreferences
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_prefKey);
      if (saved != null && saved.isNotEmpty) {
        add(saved);
      }
    } catch (e) {
      debugPrint('ApiConfig _candidateUrls prefs error: $e');
    }

    // 4. Local Development endpoints (debug mode or fallback)
    if (kDebugMode) {
      add('http://10.0.2.2:5000');
      add('http://127.0.0.1:5000');
      add('http://192.168.1.2:5000');
      add('http://192.168.8.108:5000');
    }

    return ordered;
  }

  static String _normalize(String url) {
    var u = url.trim();
    if (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    return u;
  }

  static Future<bool> _probe(String base) async {
    if (_isQa && !isAllowedQaEndpoint(base)) return false;
    final override = probeOverride;
    if (override != null) return override(base);
    final dio = Dio(
      BaseOptions(
        baseUrl: base,
        connectTimeout: _probeTimeout,
        receiveTimeout: _probeTimeout,
        headers: {'Content-Type': 'application/json'},
      ),
    );
    try {
      final response = await dio.get('/api/health');
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
