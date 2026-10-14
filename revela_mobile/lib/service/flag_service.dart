import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'auth_service.dart';
import 'api_config.dart';
import 'boundary_service.dart';
import 'connectivity_service.dart';
import 'offline_inspection_storage.dart';

/// A barangay entry returned by /api/registry/barangays.
class Barangay {
  final int? id;
  final String name;

  const Barangay({required this.id, required this.name});

  factory Barangay.fromJson(Map<String, dynamic> json) {
    return Barangay(
      id: _asInt(json['barangayID']),
      name: json['barangayName']?.toString() ?? '',
    );
  }

  static int? _asInt(dynamic v) {
    if (v is int) return v;
    return int.tryParse(v?.toString() ?? '');
  }
}

enum YellowFlagSubmissionStatus { submitted, pendingSync, needsAttention }

class YellowFlagSubmissionResult {
  final YellowFlagSubmissionStatus status;
  final MyFlag? flag;
  final String? message;
  final String clientSubmissionId;

  const YellowFlagSubmissionResult({
    required this.status,
    required this.clientSubmissionId,
    this.flag,
    this.message,
  });
}

/// A yellow flag reported by this inspector, shown on the home-page map.
class MyFlag {
  final int logID;
  final String detectedName;
  final double lat;
  final double lng;
  final String flagColor;
  final String? verificationStatus;
  final String? notes;

  const MyFlag({
    required this.logID,
    required this.detectedName,
    required this.lat,
    required this.lng,
    required this.flagColor,
    this.verificationStatus,
    this.notes,
  });

  factory MyFlag.fromJson(Map<String, dynamic> json) {
    return MyFlag(
      logID: _asInt(json['logID']),
      detectedName: json['detectedName']?.toString() ?? 'Unknown',
      lat: _asDouble(json['latitude']),
      lng: _asDouble(json['longitude']),
      flagColor: json['flagColor']?.toString() ?? 'Yellow',
      verificationStatus: json['verificationStatus']?.toString(),
      notes: json['notes']?.toString(),
    );
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    return int.tryParse(v?.toString() ?? '') ?? 0;
  }

  static double _asDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    return double.tryParse(v?.toString() ?? '') ?? double.nan;
  }
}

class InMemoryYellowFlagSnapshot {
  String? _accountId;
  List<MyFlag> _flags = const [];

  String? get accountId => _accountId;
  List<MyFlag> get flags => _flags;

  void selectAccount(String? accountId) {
    if (_accountId == accountId) return;
    _accountId = accountId;
    _flags = const [];
  }

  void replaceAfterSuccessfulRefresh(String accountId, List<MyFlag> flags) {
    if (_accountId != accountId) return;
    _flags = List.unmodifiable(flags);
  }

  void addAfterSuccessfulSubmission(MyFlag flag) {
    if (_accountId == null ||
        _flags.any((existing) => existing.logID == flag.logID)) {
      return;
    }
    _flags = List.unmodifiable([..._flags, flag]);
  }

  void retainAfterFailedRefresh(String accountId) {
    if (_accountId != accountId) selectAccount(accountId);
  }
}

/// Service for inspector-initiated yellow flag actions.
class FlagService {
  static final FlagService _instance = FlagService._internal();
  factory FlagService() => _instance;
  FlagService._internal()
    : _auth = AuthService(),
      _offlineStorage = OfflineInspectionStorage(),
      _authenticatedUserIdOverride = null,
      _backendReachableOverride = null {
    _startSyncMonitor();
  }

  @visibleForTesting
  FlagService.forTesting(
    this._auth, {
    required OfflineInspectionStorage offlineStorage,
    required Future<String?> Function() authenticatedUserId,
    required Future<bool> Function() backendReachable,
  }) : _offlineStorage = offlineStorage,
       _authenticatedUserIdOverride = authenticatedUserId,
       _backendReachableOverride = backendReachable;

  final AuthService _auth;
  final OfflineInspectionStorage _offlineStorage;
  final Future<String?> Function()? _authenticatedUserIdOverride;
  final Future<bool> Function()? _backendReachableOverride;
  final Set<String> _syncingOwners = {};
  bool _connectivityListenerAttached = false;

  /// Fetch all barangays for the dropdown.
  Future<List<Barangay>> fetchBarangays() async {
    try {
      final response = await _auth.dio.get('/api/registry/barangays');
      debugPrint('FlagService.fetchBarangays response: ${response.data}');

      // The backend may return a bare JSON array ([...]) or a wrapped
      // object ({"data": [...]}). Handle both instead of assuming one —
      // indexing a List with a String key throws a non-Dio exception that
      // was previously getting misreported as a connection error.
      final raw = response.data;
      final List<dynamic> data;
      if (raw is List) {
        data = raw;
      } else if (raw is Map<String, dynamic> && raw['data'] is List) {
        data = raw['data'] as List;
      } else {
        data = const [];
      }

      return data
          .whereType<Map<String, dynamic>>()
          .map(Barangay.fromJson)
          .where((barangay) => barangay.id != null && barangay.name.isNotEmpty)
          .toList();
    } on DioException catch (e) {
      final errorMsg =
          'FlagService.fetchBarangays error: ${e.type} - ${e.response?.statusCode} - ${e.response?.data ?? e.message}';
      debugPrint(errorMsg);
      rethrow;
    } catch (e) {
      debugPrint('FlagService.fetchBarangays unexpected error: $e');
      rethrow;
    }
  }

  /// Local fallback names come only from the bundled authoritative boundary
  /// dataset. IDs remain null until resolved from the backend registry.
  Future<List<Barangay>> fetchLocalBarangays() async {
    final boundaries = BoundaryService();
    await boundaries.loadBoundaries();
    return boundaries.localBarangayNames
        .map((name) => Barangay(id: null, name: name))
        .toList(growable: false);
  }

  /// Fetch all yellow flags submitted by this inspector.
  Future<List<MyFlag>> fetchMyYellowFlags() async {
    try {
      final response = await _auth.dio.get('/api/flags/mine');
      final raw = response.data;
      final List<dynamic> data;
      if (raw is List) {
        data = raw;
      } else if (raw is Map<String, dynamic> && raw['data'] is List) {
        data = raw['data'] as List;
      } else {
        throw const FormatException(
          'Unexpected response while fetching submitted flags.',
        );
      }
      return data
          .whereType<Map<String, dynamic>>()
          .where((f) => f['latitude'] != null && f['longitude'] != null)
          .map(MyFlag.fromJson)
          .toList();
    } on DioException catch (e) {
      debugPrint(
        'FlagService.fetchMyYellowFlags: ${e.response?.data ?? e.message}',
      );
      rethrow;
    } catch (e) {
      debugPrint('FlagService.fetchMyYellowFlags unexpected: $e');
      rethrow;
    }
  }

  /// POST /api/flags/yellow — report a suspected unregistered business.
  /// Returns the created [MyFlag] (including the logID and coords) on success.
  Future<MyFlag> reportYellowFlag({
    required String businessName,
    required double lat,
    required double lng,
    required int barangayID,
    String? notes,
  }) async {
    final response = await _auth.dio.post(
      '/api/flags/yellow',
      data: {
        'businessName': businessName,
        'lat': lat,
        'lng': lng,
        'barangayID': barangayID,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
        'flagColor': 'Yellow',
      },
    );
    final data = response.data as Map<String, dynamic>;
    return MyFlag(
      logID: data['logID'] as int? ?? 0,
      detectedName: businessName,
      lat: (data['lat'] as num?)?.toDouble() ?? lat,
      lng: (data['lng'] as num?)?.toDouble() ?? lng,
      flagColor: 'Yellow',
      notes: notes,
    );
  }

  Future<YellowFlagSubmissionResult> submitYellowFlag({
    required String businessName,
    required double lat,
    required double lng,
    required int? barangayID,
    required String barangayName,
    String? notes,
    String? clientSubmissionId,
  }) async {
    final ownerUserId = await _authenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) {
      throw StateError('Sign in again to save this Yellow Flag report.');
    }
    final submissionId = clientSubmissionId ?? _newSubmissionId();
    final now = DateTime.now().toUtc().toIso8601String();
    await _offlineStorage.saveYellowFlagDraft(
      YellowFlagDraft(
        clientSubmissionId: submissionId,
        ownerUserId: ownerUserId,
        businessName: businessName.trim(),
        lat: lat,
        lng: lng,
        barangayId: barangayID,
        barangayName: barangayName,
        notes: notes,
        createdAt: now,
        updatedAt: now,
        status: YellowFlagDraftStatus.pendingSync,
      ),
    );

    final results = await _syncPendingYellowFlags();
    return results[submissionId] ??
        YellowFlagSubmissionResult(
          status: YellowFlagSubmissionStatus.pendingSync,
          clientSubmissionId: submissionId,
          message: 'Saved on this device and waiting for a connection.',
        );
  }

  Future<List<YellowFlagDraft>> getMyYellowFlagDrafts() async {
    final ownerUserId = await _authenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) return [];
    return _offlineStorage.getYellowFlagDrafts(ownerUserId: ownerUserId);
  }

  Future<Map<String, YellowFlagSubmissionResult>>
  syncPendingYellowFlags() async {
    final ownerUserId = await _authenticatedUserId();
    if (ownerUserId == null || ownerUserId.isEmpty) return const {};
    if (_syncingOwners.contains(ownerUserId) ||
        ConnectivityService().isOffline.value ||
        !await _backendReachable()) {
      return const {};
    }

    _syncingOwners.add(ownerUserId);
    final outcomes = <String, YellowFlagSubmissionResult>{};
    try {
      await _offlineStorage.recoverInterruptedYellowFlagSyncs(
        ownerUserId: ownerUserId,
      );
      final drafts = await _offlineStorage.getYellowFlagDrafts(
        ownerUserId: ownerUserId,
      );
      for (final draft in drafts) {
        if (draft.status == YellowFlagDraftStatus.needsAttention) continue;
        if (await _authenticatedUserId() != ownerUserId) break;
        final outcome = await _syncDraft(draft, ownerUserId);
        if (outcome != null) outcomes[draft.clientSubmissionId] = outcome;
      }
    } finally {
      _syncingOwners.remove(ownerUserId);
    }
    return outcomes;
  }

  Future<Map<String, YellowFlagSubmissionResult>> _syncPendingYellowFlags() async {
    return syncPendingYellowFlags();
  }

  Future<YellowFlagSubmissionResult?> _syncDraft(
    YellowFlagDraft draft,
    String ownerUserId,
  ) async {
    var barangayId = draft.barangayId;
    if (barangayId == null) {
      try {
        final registry = await fetchBarangays();
        final key = BoundaryService.canonicalBarangayKey(draft.barangayName);
        for (final barangay in registry) {
          if (BoundaryService.canonicalBarangayKey(barangay.name) == key) {
            barangayId = barangay.id;
            break;
          }
        }
      } on DioException {
        return _retainPending(draft, ownerUserId);
      } catch (error) {
        debugPrint('FlagService could not resolve barangay ID: $error');
        return _retainPending(draft, ownerUserId);
      }
      if (barangayId == null) {
        return _retainNeedsAttention(
          draft,
          ownerUserId,
          'The selected barangay is not present in the backend registry.',
        );
      }
    }

    await _offlineStorage.updateYellowFlagDraftStatus(
      ownerUserId: ownerUserId,
      clientSubmissionId: draft.clientSubmissionId,
      status: YellowFlagDraftStatus.submitting,
    );
    try {
      if (await _authenticatedUserId() != ownerUserId) return null;
      final response = await _auth.dio.post(
        '/api/flags/yellow',
        data: {
          'businessName': draft.businessName,
          'lat': draft.lat,
          'lng': draft.lng,
          'barangayID': barangayId,
          'clientSubmissionID': draft.clientSubmissionId,
          'expectedReporterUserID': ownerUserId,
          if (draft.notes != null && draft.notes!.isNotEmpty)
            'notes': draft.notes,
          'flagColor': 'Yellow',
        },
      );
      final data = response.data;
      if (data is! Map<String, dynamic>) {
        return _retainPending(draft, ownerUserId);
      }
      final logId = int.tryParse(data['logID']?.toString() ?? '') ?? 0;
      if (logId <= 0) return _retainPending(draft, ownerUserId);
      await _offlineStorage.deleteYellowFlagDraft(
        ownerUserId: ownerUserId,
        clientSubmissionId: draft.clientSubmissionId,
      );
      return YellowFlagSubmissionResult(
        status: YellowFlagSubmissionStatus.submitted,
        clientSubmissionId: draft.clientSubmissionId,
        flag: MyFlag(
          logID: logId,
          detectedName: draft.businessName,
          lat: (data['lat'] as num?)?.toDouble() ?? draft.lat,
          lng: (data['lng'] as num?)?.toDouble() ?? draft.lng,
          flagColor: 'Yellow',
          notes: draft.notes,
        ),
      );
    } on DioException catch (error) {
      if (await _authenticatedUserId() != ownerUserId) return null;
      final statusCode = error.response?.statusCode;
      if (statusCode != null &&
          statusCode >= 400 &&
          statusCode < 500 &&
          !{401, 408, 425, 429}.contains(statusCode)) {
        return _retainNeedsAttention(
          draft,
          ownerUserId,
          _errorMessage(error),
        );
      }
      return _retainPending(draft, ownerUserId);
    } catch (error) {
      debugPrint('FlagService Yellow Flag sync failed: $error');
      return _retainPending(draft, ownerUserId);
    }
  }

  Future<YellowFlagSubmissionResult> _retainPending(
    YellowFlagDraft draft,
    String ownerUserId,
  ) async {
    await _offlineStorage.updateYellowFlagDraftStatus(
      ownerUserId: ownerUserId,
      clientSubmissionId: draft.clientSubmissionId,
      status: YellowFlagDraftStatus.pendingSync,
    );
    return YellowFlagSubmissionResult(
      status: YellowFlagSubmissionStatus.pendingSync,
      clientSubmissionId: draft.clientSubmissionId,
      message: 'Saved on this device and waiting for a connection.',
    );
  }

  Future<YellowFlagSubmissionResult> _retainNeedsAttention(
    YellowFlagDraft draft,
    String ownerUserId,
    String message,
  ) async {
    await _offlineStorage.updateYellowFlagDraftStatus(
      ownerUserId: ownerUserId,
      clientSubmissionId: draft.clientSubmissionId,
      status: YellowFlagDraftStatus.needsAttention,
      lastError: message,
    );
    return YellowFlagSubmissionResult(
      status: YellowFlagSubmissionStatus.needsAttention,
      clientSubmissionId: draft.clientSubmissionId,
      message: message,
    );
  }

  String _errorMessage(DioException error) {
    final data = error.response?.data;
    if (data is Map && data['error'] != null) {
      return data['error'].toString();
    }
    return 'The server rejected this report. Review its details and try again.';
  }

  Future<String?> _authenticatedUserId() =>
      _authenticatedUserIdOverride?.call() ?? _auth.getAuthenticatedUserId();

  Future<bool> _backendReachable() async {
    final override = _backendReachableOverride;
    if (override != null) return override();
    return await ApiConfig.ensureReachable() != null;
  }

  void _startSyncMonitor() {
    if (_connectivityListenerAttached) return;
    _connectivityListenerAttached = true;
    ConnectivityService().isOffline.addListener(_onConnectivityChanged);
    Timer.periodic(
      const Duration(seconds: 30),
      (_) => unawaited(syncPendingYellowFlags()),
    );
  }

  void _onConnectivityChanged() {
    if (!ConnectivityService().isOffline.value) {
      unawaited(syncPendingYellowFlags());
    }
  }

  static String _newSubmissionId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes.map((byte) => byte.toRadixString(16).padLeft(2, '0'));
    final value = hex.join();
    return '${value.substring(0, 8)}-${value.substring(8, 12)}-'
        '${value.substring(12, 16)}-${value.substring(16, 20)}-'
        '${value.substring(20)}';
  }
}
