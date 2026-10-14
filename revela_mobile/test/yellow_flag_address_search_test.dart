import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/yellow_flag_address_search.dart';

class _AddressSearchAdapter implements HttpClientAdapter {
  Map<String, dynamic>? requestBody;
  String? requestPath;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requestPath = options.path;
    final rawBody = options.data;
    requestBody = rawBody is Map<String, dynamic>
        ? rawBody
        : jsonDecode(rawBody as String) as Map<String, dynamic>;
    final responseData = options.path.endsWith('/reverse-geocode')
        ? {'formattedAddress': '115 Templo Avenue, Barangay II, Philippines'}
        : {
            'results': [
              {
                'formattedAddress': '12 Main Street, Barangay II, Philippines',
                'latitude': 13.96,
                'longitude': 121.11,
                'placeId': 'place-1',
              },
            ],
          };
    return ResponseBody.fromString(
      jsonEncode(responseData),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  test(
    'searches with the selected barangay and returns selectable addresses',
    () async {
      final adapter = _AddressSearchAdapter();
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
        ..httpClientAdapter = adapter;
      final service = YellowFlagAddressSearchService(
        dio: dio,
        isOffline: () async => false,
      );

      final results = await service.search(
        streetAddress: '12 Main Street',
        barangay: 'Barangay II',
      );

      expect(adapter.requestBody, {
        'streetAddress': '12 Main Street',
        'barangay': 'Barangay II',
      });
      expect(results, hasLength(1));
      expect(results.single.formattedAddress, contains('12 Main Street'));
      expect(results.single.latitude, 13.96);
      expect(results.single.longitude, 121.11);
    },
  );

  test('reports offline without making a request', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    final service = YellowFlagAddressSearchService(
      dio: dio,
      isOffline: () async => true,
    );

    await expectLater(
      service.search(streetAddress: 'Main Street', barangay: 'Barangay II'),
      throwsA(
        isA<YellowFlagAddressSearchException>().having(
          (error) => error.failure,
          'failure',
          YellowFlagAddressSearchFailure.offline,
        ),
      ),
    );
  });

  test('searches municipality-wide before a barangay is known', () async {
    final adapter = _AddressSearchAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
      ..httpClientAdapter = adapter;
    final service = YellowFlagAddressSearchService(
      dio: dio,
      isOffline: () async => false,
    );

    await service.search(streetAddress: '115 Templo Avenue');

    expect(adapter.requestBody, {'streetAddress': '115 Templo Avenue'});
  });

  test('reverse geocodes the current GPS coordinates', () async {
    final adapter = _AddressSearchAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
      ..httpClientAdapter = adapter;
    final service = YellowFlagAddressSearchService(
      dio: dio,
      isOffline: () async => false,
    );

    final address = await service.reverseGeocode(
      latitude: 13.96,
      longitude: 121.11,
    );

    expect(adapter.requestPath, '/api/flags/reverse-geocode');
    expect(adapter.requestBody, {'latitude': 13.96, 'longitude': 121.11});
    expect(address, '115 Templo Avenue, Barangay II, Philippines');
  });
}
