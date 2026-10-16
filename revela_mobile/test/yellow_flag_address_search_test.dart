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
                'locationType': 'ROOFTOP',
                'resultTypes': ['street_address'],
                'partialMatch': false,
                'providerResultCount': 1,
                'addressComponents': [
                  {
                    'long_name': '12',
                    'short_name': '12',
                    'types': ['street_number'],
                  },
                  {
                    'long_name': 'Main Street',
                    'short_name': 'Main St',
                    'types': ['route'],
                  },
                ],
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
      expect(results.single.locationType, 'ROOFTOP');
      expect(results.single.partialMatch, isFalse);
      expect(results.single.providerResultCount, 1);
      expect(results.single.resultTypes, ['street_address']);
      expect(results.single.addressComponents.last.shortName, 'Main St');
      expect(
        YellowFlagAddressCandidate.resolveAddress('12 Main St.', results),
        results.single,
      );
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

  Map<String, dynamic> preciseResult() => {
    'formattedAddress': '12 Main Street, Mataasnakahoy, Batangas, Philippines',
    'latitude': 13.96,
    'longitude': 121.11,
    'placeId': 'place-1',
    'locationType': 'ROOFTOP',
    'resultTypes': ['street_address'],
    'partialMatch': false,
    'providerResultCount': 1,
    'addressComponents': [
      {
        'long_name': '12',
        'short_name': '12',
        'types': ['street_number'],
      },
      {
        'long_name': 'Main Street',
        'short_name': 'Main St',
        'types': ['route'],
      },
      {
        'long_name': 'Mataasnakahoy',
        'short_name': 'Mataasnakahoy',
        'types': ['locality', 'political'],
      },
    ],
  };

  test('only a corroborated, unambiguous rooftop address is auto-resolved', () {
    final candidate = YellowFlagAddressCandidate.fromJson(preciseResult());
    for (final input in ['12 Main Street', '#12 Main St., Mataasnakahoy']) {
      expect(
        YellowFlagAddressCandidate.resolveAddress(input, [candidate]),
        candidate,
      );
    }
    for (final input in [
      'Main Street',
      '13 Main Street',
      '12 Other Street',
      'Behind 12 Main Street',
      '12 Main Street unlisted alley',
    ]) {
      expect(
        YellowFlagAddressCandidate.resolveAddress(input, [candidate]),
        isNull,
        reason: input,
      );
    }
    expect(
      YellowFlagAddressCandidate.resolveAddress('12 Main Street', []),
      isNull,
    );
    expect(
      YellowFlagAddressCandidate.resolveAddress('12 Main Street', [
        candidate,
        candidate,
      ]),
      isNull,
    );
  });

  for (final entry in <String, Map<String, dynamic>>{
    'barangay centroid': {
      'locationType': 'APPROXIMATE',
      'resultTypes': ['sublocality_level_1', 'sublocality', 'political'],
    },
    'municipality centroid': {
      'resultTypes': ['locality', 'political'],
    },
    'broad street center': {
      'locationType': 'GEOMETRIC_CENTER',
      'resultTypes': ['route'],
    },
    'route even with rooftop metadata': {
      'resultTypes': ['route'],
    },
    'interpolated address': {'locationType': 'RANGE_INTERPOLATED'},
    'partial match': {'partialMatch': true},
    'unknown partial match': {'partialMatch': null},
    'ambiguous before filtering': {'providerResultCount': 2},
    'unknown original result count': {'providerResultCount': null},
    'missing precision': {'locationType': null},
    'missing components': {'addressComponents': null},
    'missing place ID': {'placeId': ''},
  }.entries) {
    test('${entry.key} is never accepted as an exact business', () {
      final candidate = YellowFlagAddressCandidate.fromJson({
        ...preciseResult(),
        ...entry.value,
      });
      expect(
        YellowFlagAddressCandidate.resolveAddress('12 Main Street', [
          candidate,
        ]),
        isNull,
      );
    });
  }

  test('a named premise needs a matching name, not a nearby landmark', () {
    final candidate = YellowFlagAddressCandidate.fromJson({
      ...preciseResult(),
      'resultTypes': ['premise'],
      'addressComponents': [
        {
          'long_name': 'Templo Building',
          'short_name': 'Templo Bldg',
          'types': ['premise'],
        },
      ],
    });
    expect(
      YellowFlagAddressCandidate.resolveAddress('Templo Bldg', [candidate]),
      candidate,
    );
    expect(
      YellowFlagAddressCandidate.resolveAddress('Behind Templo Building', [
        candidate,
      ]),
      isNull,
    );
  });

  test('a generic building or unit number is not a named premise', () {
    for (final component in [
      {
        'long_name': 'Building',
        'short_name': 'Bldg',
        'types': ['premise'],
      },
      {
        'long_name': '101',
        'short_name': '101',
        'types': ['subpremise'],
      },
    ]) {
      final candidate = YellowFlagAddressCandidate.fromJson({
        ...preciseResult(),
        'resultTypes': ['premise'],
        'addressComponents': [component],
      });
      expect(
        YellowFlagAddressCandidate.resolveAddress(
          component['long_name'] as String,
          [candidate],
        ),
        isNull,
      );
    }
  });
}
