import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'auth_service.dart';

/// A barangay entry returned by /api/registry/barangays.
class Barangay {
  final int id;
  final String name;

  const Barangay({required this.id, required this.name});

  factory Barangay.fromJson(Map<String, dynamic> json) {
    return Barangay(
      id: _asInt(json['barangayID']),
      name: json['barangayName']?.toString() ?? '',
    );
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    return int.tryParse(v?.toString() ?? '') ?? 0;
  }
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
    return double.tryParse(v?.toString() ?? '') ?? 0.0;
  }
}

/// Service for inspector-initiated yellow flag actions.
class FlagService {
  static final FlagService _instance = FlagService._internal();
  factory FlagService() => _instance;
  FlagService._internal();

  final AuthService _auth = AuthService();

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
        data = const [];
      }
      return data
          .whereType<Map<String, dynamic>>()
          .where((f) => f['latitude'] != null && f['longitude'] != null)
          .map(MyFlag.fromJson)
          .toList();
    } on DioException catch (e) {
      debugPrint('FlagService.fetchMyYellowFlags: ${e.response?.data ?? e.message}');
      return [];
    } catch (e) {
      debugPrint('FlagService.fetchMyYellowFlags unexpected: $e');
      return [];
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
    try {
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
    } on DioException catch (e) {
      debugPrint(
        'FlagService.reportYellowFlag: ${e.response?.data ?? e.message}',
      );
      rethrow;
    }
  }
}