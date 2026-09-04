import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Resolves the Flask API base URL for emulator, USB (adb reverse), and Wi‑Fi.
class ApiConfig {
  static const String _prefKey = 'api_base_url';
  static const String _compileTimeBase = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'https://api.revelasys.site',
  );

  static const Duration _probeTimeout = Duration(seconds: 2);

  static String? _resolvedBase;

  /// Active base URL (no trailing slash), e.g. `https://api.revelasys.site`.
  static String get apiBase {
    if (_resolvedBase != null) return _resolvedBase!;
    if (_compileTimeBase.trim().isNotEmpty) {
      return _normalize(_compileTimeBase);
    }
    return 'https://api.revelasys.site';
  }

  static Future<void> initialize() async {
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

    if (_resolvedBase != null && await _probe(_resolvedBase!)) {
      return;
    }

    final discovered = await discover();
    if (discovered != null) {
      _resolvedBase = discovered;
    } else {
      _resolvedBase = 'https://api.revelasys.site';
    }
  }

  /// Tries known dev endpoints until one responds to `/api/health`.
  static Future<String?> discover() async {
    for (final candidate in await _candidateUrls()) {
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

  /// Verifies connectivity; runs [discover] if the current base is down.
  static Future<String?> ensureReachable() async {
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
