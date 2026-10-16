import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'auth_service.dart';
import 'connectivity_service.dart';

class YellowFlagAddressComponent {
  const YellowFlagAddressComponent({
    required this.longName,
    required this.shortName,
    required this.types,
  });

  final String longName;
  final String shortName;
  final List<String> types;

  factory YellowFlagAddressComponent.fromJson(
    Map<String, dynamic> json,
  ) => YellowFlagAddressComponent(
    longName: json['long_name'] is String ? json['long_name'] as String : '',
    shortName: json['short_name'] is String ? json['short_name'] as String : '',
    types: _stringList(json['types']),
  );
}

List<String> _stringList(dynamic value) =>
    value is List && value.every((v) => v is String)
    ? value.cast<String>()
    : const [];

class YellowFlagAddressCandidate {
  const YellowFlagAddressCandidate({
    required this.formattedAddress,
    required this.latitude,
    required this.longitude,
    this.placeId = '',
    this.locationType = '',
    this.resultTypes = const [],
    this.partialMatch,
    this.addressComponents = const [],
    this.providerResultCount,
  });

  final String formattedAddress;
  final double latitude;
  final double longitude;
  final String placeId;
  final String locationType;
  final List<String> resultTypes;
  final bool? partialMatch;
  final List<YellowFlagAddressComponent> addressComponents;
  final int? providerResultCount;

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
      locationType: json['locationType'] is String
          ? json['locationType'] as String
          : '',
      resultTypes: _stringList(json['resultTypes']),
      partialMatch: json['partialMatch'] is bool
          ? json['partialMatch'] as bool
          : null,
      addressComponents: json['addressComponents'] is List
          ? (json['addressComponents'] as List)
                .whereType<Map<String, dynamic>>()
                .map(YellowFlagAddressComponent.fromJson)
                .toList(growable: false)
          : const [],
      providerResultCount: json['providerResultCount'] is int
          ? json['providerResultCount'] as int
          : null,
    );
  }

  /// Deliberately conservative: neither result order nor a place ID alone
  /// proves business-level precision. The form also checks official polygons.
  static YellowFlagAddressCandidate? resolveAddress(
    String streetAddress,
    List<YellowFlagAddressCandidate> candidates,
  ) {
    if (candidates.length != 1) return null;
    final candidate = candidates.single;
    if (candidate.providerResultCount != 1 ||
        candidate.partialMatch != false ||
        candidate.locationType != 'ROOFTOP' ||
        candidate.placeId.trim().isEmpty ||
        !candidate.resultTypes.any(
          const {
            'street_address',
            'premise',
            'subpremise',
            'establishment',
            'point_of_interest',
          }.contains,
        ) ||
        candidate.resultTypes.any(
          (type) =>
              type == 'political' ||
              type == 'route' ||
              type == 'intersection' ||
              type == 'plus_code' ||
              type == 'locality' ||
              type.startsWith('administrative_area') ||
              type.startsWith('sublocality') ||
              type.startsWith('postal_code'),
        )) {
      return null;
    }

    final input = _addressWords(streetAddress);
    // A nearby landmark is not the business itself, even if that landmark has
    // a rooftop result. Unmatched descriptive text also fails closed below.
    if (input.isEmpty ||
        input.any(
          const {
            'near',
            'nearby',
            'behind',
            'beside',
            'opposite',
            'across',
            'likod',
            'tabi',
            'tapat',
            'malapit',
          }.contains,
        )) {
      return null;
    }

    bool includesComponent(YellowFlagAddressComponent component) {
      final words = _addressWords(component.longName);
      return words.isNotEmpty && input.containsAll(words);
    }

    final numberedStreet =
        candidate.addressComponents.any(
          (component) =>
              component.types.contains('street_number') &&
              includesComponent(component),
        ) &&
        candidate.addressComponents.any(
          (component) =>
              component.types.contains('route') && includesComponent(component),
        );
    final namedPremise = candidate.addressComponents.any((component) {
      final nameWords = _addressWords(component.longName);
      // A unit number or a generic "building" is not a named business/premise.
      final hasName = nameWords.any(
        (word) =>
            RegExp(r'[a-zñ]').hasMatch(word) &&
            !const {
              'building',
              'unit',
              'suite',
              'floor',
              'store',
              'shop',
              'chapel',
              'church',
              'premise',
            }.contains(word),
      );
      return component.types.any(
            const {'premise', 'establishment', 'point_of_interest'}.contains,
          ) &&
          hasName &&
          includesComponent(component);
    });
    final componentWords = candidate.addressComponents
        .expand(
          (component) => {
            ..._addressWords(component.longName),
            ..._addressWords(component.shortName),
          },
        )
        .toSet();
    if ((!numberedStreet && !namedPremise) ||
        !componentWords.containsAll(input)) {
      return null;
    }
    return candidate;
  }

  static Set<String> _addressWords(String value) {
    const aliases = {
      'st': 'street',
      'ave': 'avenue',
      'av': 'avenue',
      'rd': 'road',
      'brgy': 'barangay',
      'bgy': 'barangay',
      'bldg': 'building',
    };
    return value
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9ñ]+'), ' ')
        .split(' ')
        .where((word) => word.isNotEmpty)
        .map((word) => aliases[word] ?? word)
        .toSet();
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
