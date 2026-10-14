import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'auth_service.dart';
import 'connectivity_service.dart';

class YellowFlagAddressCandidate {
  const YellowFlagAddressCandidate({
    required this.formattedAddress,
    required this.latitude,
    required this.longitude,
    this.placeId = '',
  });

  final String formattedAddress;
  final double latitude;
  final double longitude;
  final String placeId;

  factory YellowFlagAddressCandidate.fromJson(Map<String, dynamic> json) {
    final address = json['formattedAddress'];
    final latitude = _asDouble(json['latitude']);
    final longitude = _asDouble(json['longitude']);
    if (address is! String ||
        address.trim().isEmpty ||
        latitude == null ||
        longitude == null ||
        !latitude.isFinite ||
        !longitude.isFinite ||
        latitude < -90 ||
        latitude > 90 ||
        longitude < -180 ||
        longitude > 180) {
      throw const FormatException('Invalid address search candidate.');
    }
    return YellowFlagAddressCandidate(
      formattedAddress: address.trim(),
      latitude: latitude,
      longitude: longitude,
      placeId: json['placeId']?.toString() ?? '',
    );
  }

  static double? _asDouble(dynamic value) {
    if (value is num) return value.toDouble();
    return double.tryParse(value?.toString() ?? '');
  }
}

enum YellowFlagAddressSearchFailure { offline, network, unavailable }

class YellowFlagAddressSearchException implements Exception {
  const YellowFlagAddressSearchException(this.failure);

  final YellowFlagAddressSearchFailure failure;
}

class YellowFlagAddressSearchService {
  YellowFlagAddressSearchService({Dio? dio, Future<bool> Function()? isOffline})
    : _dio = dio ?? AuthService().dio,
      _isOffline = isOffline ?? _deviceIsOffline;

  final Dio _dio;
  final Future<bool> Function() _isOffline;

  Future<List<YellowFlagAddressCandidate>> search({
    required String streetAddress,
    String? barangay,
  }) async {
    try {
      if (await _isOffline()) {
        throw const YellowFlagAddressSearchException(
          YellowFlagAddressSearchFailure.offline,
        );
      }
      final requestData = <String, dynamic>{'streetAddress': streetAddress};
      if (barangay != null && barangay.trim().isNotEmpty) {
        requestData['barangay'] = barangay.trim();
      }
      final response = await _dio.post(
        '/api/flags/location-search',
        data: requestData,
      );
      final data = response.data;
      if (data is! Map<String, dynamic> || data['results'] is! List) {
        throw const FormatException('Invalid address search response.');
      }
      return (data['results'] as List)
          .map((item) {
            if (item is! Map<String, dynamic>) {
              throw const FormatException('Invalid address search result.');
            }
            return YellowFlagAddressCandidate.fromJson(item);
          })
          .toList(growable: false);
    } on YellowFlagAddressSearchException {
      rethrow;
    } on DioException catch (error) {
      final failure = switch (error.type) {
        DioExceptionType.connectionTimeout ||
        DioExceptionType.connectionError ||
        DioExceptionType.sendTimeout ||
        DioExceptionType.receiveTimeout =>
          await _isOffline()
              ? YellowFlagAddressSearchFailure.offline
              : YellowFlagAddressSearchFailure.network,
        _ => YellowFlagAddressSearchFailure.unavailable,
      };
      throw YellowFlagAddressSearchException(failure);
    } on FormatException {
      throw const YellowFlagAddressSearchException(
        YellowFlagAddressSearchFailure.unavailable,
      );
    }
  }

  Future<String?> reverseGeocode({
    required double latitude,
    required double longitude,
  }) async {
    try {
      if (await _isOffline()) {
        throw const YellowFlagAddressSearchException(
          YellowFlagAddressSearchFailure.offline,
        );
      }
      final response = await _dio.post(
        '/api/flags/reverse-geocode',
        data: {'latitude': latitude, 'longitude': longitude},
      );
      final data = response.data;
      if (data is! Map<String, dynamic>) {
        throw const FormatException('Invalid reverse geocoding response.');
      }
      final address = data['formattedAddress'];
      if (address == null) return null;
      if (address is! String || address.trim().isEmpty) {
        throw const FormatException('Invalid reverse geocoding address.');
      }
      return address.trim();
    } on YellowFlagAddressSearchException {
      rethrow;
    } on DioException catch (error) {
      final failure = switch (error.type) {
        DioExceptionType.connectionTimeout ||
        DioExceptionType.connectionError ||
        DioExceptionType.sendTimeout ||
        DioExceptionType.receiveTimeout =>
          await _isOffline()
              ? YellowFlagAddressSearchFailure.offline
              : YellowFlagAddressSearchFailure.network,
        _ => YellowFlagAddressSearchFailure.unavailable,
      };
      throw YellowFlagAddressSearchException(failure);
    } on FormatException {
      throw const YellowFlagAddressSearchException(
        YellowFlagAddressSearchFailure.unavailable,
      );
    }
  }

  static Future<bool> _deviceIsOffline() async {
    if (ConnectivityService.instance.isOffline.value) return true;
    try {
      final results = await Connectivity().checkConnectivity();
      return results.isEmpty ||
          !results.any((result) => result != ConnectivityResult.none);
    } on Exception catch (error) {
      debugPrint('Could not check connectivity before address search: $error');
      return false;
    }
  }
}
