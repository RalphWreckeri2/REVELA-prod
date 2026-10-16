import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart';
import 'package:revela_mobile/pages/home_page.dart';
import 'package:revela_mobile/service/boundary_service.dart';
import 'package:revela_mobile/service/flag_service.dart';
import 'package:revela_mobile/service/inspection_location_service.dart';
import 'package:revela_mobile/service/offline_inspection_storage.dart';
import 'package:revela_mobile/service/yellow_flag_address_search.dart';

const _businessPin = LatLng(13.960630, 121.113447);
const _movedPin = LatLng(13.960700, 121.113500);
const _manualAddress = 'Purok Makisig, behind the unnamed chapel';
const _gpsAddress = '115 Templo Avenue, Barangay II, Mataasnakahoy, Batangas';
const _fallback =
    'We couldn’t pinpoint this address. Choose the business location on the map or use your current location.';

YellowFlagAddressCandidate _preciseAddress({
  String number = '115',
  LatLng pin = _businessPin,
}) => YellowFlagAddressCandidate.fromJson({
  'formattedAddress':
      '$number Templo Avenue, Barangay II, Mataasnakahoy, Batangas',
  'latitude': pin.latitude,
  'longitude': pin.longitude,
  'placeId': 'place-$number',
  'locationType': 'ROOFTOP',
  'partialMatch': false,
  'resultTypes': ['street_address'],
  'providerResultCount': 1,
  'addressComponents': [
    {
      'long_name': number,
      'short_name': number,
      'types': ['street_number'],
    },
    {
      'long_name': 'Templo Avenue',
      'short_name': 'Templo Ave',
      'types': ['route'],
    },
  ],
});

// Only the native map surface is stubbed. Tests exercise the actual picker,
// map/marker callbacks, confirmation route result, form and submit handler.
class _HeadlessMapPlatform extends GoogleMapsFlutterPlatform {
  @override
  Widget buildViewWithConfiguration(
    int creationId,
    PlatformViewCreatedCallback onPlatformViewCreated, {
    required MapWidgetConfiguration widgetConfiguration,
    MapConfiguration mapConfiguration = const MapConfiguration(),
    MapObjects mapObjects = const MapObjects(),
  }) => const ColoredBox(color: Colors.grey);
}

class _Flags implements FlagService {
  final submissions = <Map<String, dynamic>>[];
  final accepted = <MyFlag>[];
  List<YellowFlagDraft> drafts = [];
  Completer<YellowFlagSubmissionResult>? pendingSubmission;
  final barangays = const [
    Barangay(id: 2, name: 'Barangay II'),
    Barangay(id: 3, name: 'Barangay II-A'),
  ];

  @override
  Future<List<Barangay>> fetchBarangays() async => barangays;

  @override
  Future<List<YellowFlagDraft>> getMyYellowFlagDrafts() async => drafts;

  @override
  Future<YellowFlagSubmissionResult> submitYellowFlag({
    required String businessName,
    required String businessAddress,
    YellowFlagLocationMethod locationMethod =
        YellowFlagLocationMethod.savedReport,
    required double lat,
    required double lng,
    required int? barangayID,
    required String barangayName,
    String? notes,
    String? clientSubmissionId,
  }) async {
    submissions.add({
      'businessName': businessName,
      'businessAddress': businessAddress,
      'locationMethod': locationMethod,
      'lat': lat,
      'lng': lng,
      'barangayID': barangayID,
    });
    return pendingSubmission?.future ??
        YellowFlagSubmissionResult(
          status: YellowFlagSubmissionStatus.submitted,
          clientSubmissionId: 'test-report',
          flag: MyFlag(
            logID: 41,
            detectedName: businessName,
            businessAddress: businessAddress,
            lat: lat,
            lng: lng,
            flagColor: 'Yellow',
          ),
        );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Addresses implements YellowFlagAddressSearchService {
  List<YellowFlagAddressCandidate> candidates = [];
  Completer<List<YellowFlagAddressCandidate>>? pendingSearch;
  Completer<String?>? pendingReverse;
  YellowFlagAddressSearchFailure? searchFailure;
  YellowFlagAddressSearchFailure? reverseFailure;
  String? reverseAddress = _gpsAddress;
  Future<List<YellowFlagAddressCandidate>> Function(String, String?)? onSearch;
  final queries = <Map<String, String?>>[];
  int searches = 0;
  int reverseLookups = 0;

  @override
  Future<List<YellowFlagAddressCandidate>> search({
    required String streetAddress,
    String? barangay,
  }) async {
    searches++;
    queries.add({'streetAddress': streetAddress, 'barangay': barangay});
    if (searchFailure != null) {
      throw YellowFlagAddressSearchException(searchFailure!);
    }
    if (onSearch != null) return onSearch!(streetAddress, barangay);
    return pendingSearch?.future ?? candidates;
  }

  @override
  Future<String?> reverseGeocode({
    required double latitude,
    required double longitude,
  }) async {
    reverseLookups++;
    if (reverseFailure != null) {
      throw YellowFlagAddressSearchException(reverseFailure!);
    }
    return pendingReverse?.future ?? reverseAddress;
  }
}

class _Gps implements InspectionLocationPlatform {
  LocationPermission permission = LocationPermission.deniedForever;
  int serviceChecks = 0;
  int permissionRequests = 0;
  int fixRequests = 0;
  Completer<InspectionLocationFix>? pendingFix;
  InspectionLocationFix fix = const InspectionLocationFix(
    latitude: 13.960630,
    longitude: 121.113447,
    accuracy: 10,
  );

  @override
  Future<bool> isLocationServiceEnabled() async {
    serviceChecks++;
    return true;
  }

  @override
  Future<LocationPermission> checkPermission() async => permission;

  @override
  Future<LocationPermission> requestPermission() async {
    permissionRequests++;
    return permission;
  }

  @override
  Future<InspectionLocationFix> getCurrentFix(Duration timeout) async {
    fixRequests++;
    return pendingFix?.future ?? fix;
  }

  @override
  Future<bool> openAppSettings() async => true;

  @override
  Future<bool> openLocationSettings() async => true;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late GoogleMapsFlutterPlatform originalMaps;
  late _Flags flags;
  late _Addresses addresses;
  late _Gps gps;

  setUpAll(() async => BoundaryService().loadBoundaries());

  setUp(() {
    originalMaps = GoogleMapsFlutterPlatform.instance;
    GoogleMapsFlutterPlatform.instance = _HeadlessMapPlatform();
    flags = _Flags();
    addresses = _Addresses();
    gps = _Gps();
  });

  tearDown(() => GoogleMapsFlutterPlatform.instance = originalMaps);

  Finder nameField() => find.byType(TextFormField).at(0);
  Finder addressField() => find.byType(TextFormField).at(1);
  Finder submitButton() =>
      find.widgetWithText(ElevatedButton, 'Submit Yellow Flag');
  Finder confirmButton() =>
      find.widgetWithText(ElevatedButton, 'Confirm business location');
  GoogleMap map(WidgetTester tester) =>
      tester.widget<GoogleMap>(find.byType(GoogleMap));
  bool canSubmit(WidgetTester tester) =>
      tester.widget<ElevatedButton>(submitButton()).onPressed != null;
  bool canConfirm(WidgetTester tester) =>
      tester.widget<ElevatedButton>(confirmButton()).onPressed != null;

  Future<void> tap(
    WidgetTester tester,
    Finder finder, {
    bool settle = true,
  }) async {
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    if (settle) {
      await tester.pumpAndSettle();
    } else {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  Future<void> openForm(WidgetTester tester, {bool fillAddress = true}) async {
    tester.view.physicalSize = const Size(900, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (_) => YellowFlagSheet(
                  flagService: flags,
                  addressSearchService: addresses,
                  locationService: InspectionLocationService(platform: gps),
                  onSuccess: flags.accepted.add,
                  onPendingSync: () {},
                ),
              ),
              child: const Text('Open form'),
            ),
          ),
        ),
      ),
    );
    await tap(tester, find.text('Open form'));
    await tester.enterText(nameField(), 'Offsite Shop');
    if (fillAddress) await tester.enterText(addressField(), _manualAddress);
    await tester.pump();
  }

  Future<void> openMap(WidgetTester tester) =>
      tap(tester, find.text('Choose location on map'));

  Future<void> selectPin(WidgetTester tester, LatLng pin) async {
    map(tester).onTap!(pin);
    await tester.pumpAndSettle();
  }

  Future<void> confirmManualPin(WidgetTester tester) async {
    await openMap(tester);
    await selectPin(tester, _businessPin);
    await tap(tester, confirmButton());
  }

  Future<void> resolveAddress(
    WidgetTester tester, {
    String address = '115 Templo Avenue',
  }) async {
    await tester.enterText(addressField(), address);
    await tester.pump(const Duration(milliseconds: 800));
    await tester.pumpAndSettle();
  }

  Future<void> chooseBarangay(WidgetTester tester, Barangay barangay) async {
    tester
        .widget<DropdownButton<Barangay>>(find.byType(DropdownButton<Barangay>))
        .onChanged!(barangay);
    await tester.pump();
  }

  testWidgets(
    'precise manual address enables submit without suggestions or map',
    (tester) async {
      addresses.candidates = [_preciseAddress()];
      await openForm(tester, fillAddress: false);
      await chooseBarangay(tester, flags.barangays.first);
      await resolveAddress(tester, address: '115 Templo Ave.');
      expect(find.text('Location found'), findsOneWidget);
      expect(find.text('Inspect or adjust location'), findsOneWidget);
      expect(find.byType(GoogleMap), findsNothing);
      expect(canSubmit(tester), isTrue);
      expect(addresses.queries, [
        {'streetAddress': '115 Templo Ave.', 'barangay': 'Barangay II'},
      ]);
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], '115 Templo Ave.');
      expect(flags.submissions.single['lat'], _businessPin.latitude);
      expect(flags.submissions.single['lng'], _businessPin.longitude);
      expect(gps.serviceChecks, 0);
    },
  );

  testWidgets(
    'unsearchable address and confirmed map pin submit without GPS permission',
    (tester) async {
      await openForm(tester);
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(addresses.searches, 1);
      await openMap(tester);
      expect(
        map(tester).initialCameraPosition.target,
        const LatLng(13.9667, 121.1167),
      );
      expect(map(tester).markers, isEmpty);
      expect(map(tester).myLocationEnabled, isFalse);
      expect(map(tester).myLocationButtonEnabled, isFalse);
      expect(
        canConfirm(tester),
        isFalse,
        reason: 'The municipal view is not a selected pin',
      );
      await selectPin(tester, _businessPin);
      expect(flags.submissions, isEmpty);
      await tap(tester, confirmButton());
      expect(canSubmit(tester), isTrue);
      await tap(tester, submitButton());
      expect(flags.submissions.single, {
        'businessName': 'Offsite Shop',
        'businessAddress': _manualAddress,
        'locationMethod': YellowFlagLocationMethod.manualPin,
        'lat': _businessPin.latitude,
        'lng': _businessPin.longitude,
        'barangayID': 2,
      });
      expect(flags.accepted, hasLength(1));
      expect(gps.serviceChecks, 0);
      expect(gps.permissionRequests, 0);
      expect(gps.fixRequests, 0);
      expect(addresses.reverseLookups, 0);
    },
  );

  testWidgets('unresolvable address shows fallback and cannot submit', (
    tester,
  ) async {
    await openForm(tester);
    await tester.pump(const Duration(milliseconds: 800));
    await tester.pumpAndSettle();
    expect(find.text(_fallback), findsOneWidget);
    expect(canSubmit(tester), isFalse);
    await tap(tester, submitButton());
    expect(flags.submissions, isEmpty);
    expect(gps.serviceChecks, 0);
  });

  for (final address in ['SM', List.filled(255, 'x').join()]) {
    testWidgets(
      'valid ${address.length}-character address is sent intact for resolution',
      (tester) async {
        await openForm(tester, fillAddress: false);
        await resolveAddress(tester, address: address);
        expect(addresses.queries.single['streetAddress'], address);
        expect(
          tester.widget<TextFormField>(addressField()).controller!.text,
          address,
        );
        expect(canSubmit(tester), isFalse);
        expect(find.text(_fallback), findsOneWidget);
      },
    );
  }

  testWidgets(
    'address edits preserve a confirmed manual pin without unnecessary lookups',
    (tester) async {
      await openForm(tester);
      await confirmManualPin(tester);
      final searchesBeforeEditing = addresses.searches;
      await tester.enterText(
        addressField(),
        'Unlisted alley beside the old mango tree',
      );
      await tester.pump(const Duration(milliseconds: 800));
      expect(canSubmit(tester), isTrue);
      expect(addresses.searches, searchesBeforeEditing);
      await tap(tester, submitButton());
      expect(
        flags.submissions.single['businessAddress'],
        'Unlisted alley beside the old mango tree',
      );
      expect(flags.submissions.single['lat'], _businessPin.latitude);
      expect(flags.submissions.single['lng'], _businessPin.longitude);
    },
  );

  testWidgets(
    'moving a pin needs confirmation; cancel keeps the previously confirmed pin',
    (tester) async {
      await openForm(tester);
      await confirmManualPin(tester);
      await openMap(tester);
      var marker = map(tester).markers.single;
      marker.onDragStart!(_businessPin);
      await tester.pump();
      expect(canConfirm(tester), isFalse);
      marker.onDragEnd!(_movedPin);
      await tester.pumpAndSettle();
      expect(map(tester).markers.single.position, _movedPin);
      expect(flags.submissions, isEmpty);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isTrue);
      await openMap(tester);
      expect(map(tester).markers.single.position, _businessPin);
      marker = map(tester).markers.single;
      marker.onDragEnd!(_movedPin);
      await tester.pumpAndSettle();
      await tap(tester, confirmButton());
      await tap(tester, submitButton());
      expect(flags.submissions.single['lat'], _movedPin.latitude);
      expect(flags.submissions.single['lng'], _movedPin.longitude);
    },
  );

  for (final fillAddress in [false, true]) {
    testWidgets(
      'current location restores address and barangay auto-fill (existing address: $fillAddress)',
      (tester) async {
        gps.permission = LocationPermission.whileInUse;
        await openForm(tester, fillAddress: fillAddress);
        if (fillAddress) await confirmManualPin(tester);
        await tap(tester, find.text('Use current location'));
        expect(find.byType(GoogleMap), findsNothing);
        expect(
          find.textContaining('Location set to Barangay II · Mataasnakahoy'),
          findsOneWidget,
        );
        expect(
          tester.widget<TextFormField>(addressField()).controller!.text,
          _gpsAddress,
        );
        expect(
          tester
              .widget<DropdownButton<Barangay>>(
                find.byType(DropdownButton<Barangay>),
              )
              .value!
              .name,
          'Barangay II',
        );
        expect(flags.submissions, isEmpty);
        expect(canSubmit(tester), isTrue);
        await tap(tester, submitButton());
        expect(gps.fixRequests, 1);
        expect(flags.submissions.single['businessAddress'], _gpsAddress);
        expect(
          flags.submissions.single['locationMethod'],
          YellowFlagLocationMethod.gps,
        );
        expect(flags.submissions.single['lat'], _businessPin.latitude);
        expect(flags.submissions.single['lng'], _businessPin.longitude);
        expect(addresses.reverseLookups, 1);
      },
    );
  }

  testWidgets('failed GPS request leaves a confirmed manual pin usable', (
    tester,
  ) async {
    await openForm(tester);
    await confirmManualPin(tester);
    await tap(tester, find.text('Use current location'));
    expect(
      find.textContaining('Location permission is blocked.'),
      findsOneWidget,
    );
    expect(canSubmit(tester), isTrue);
    await tap(tester, submitButton());
    expect(gps.serviceChecks, 1);
    expect(flags.submissions.single['lat'], _businessPin.latitude);
    expect(flags.submissions.single['lng'], _businessPin.longitude);
    expect(flags.submissions.single['businessAddress'], _manualAddress);
  });

  testWidgets('outside-boundary GPS cannot replace a confirmed manual pin', (
    tester,
  ) async {
    gps.permission = LocationPermission.whileInUse;
    gps.fix = const InspectionLocationFix(
      latitude: 14.6,
      longitude: 121,
      accuracy: 10,
    );
    await openForm(tester);
    await confirmManualPin(tester);
    await tap(tester, find.text('Use current location'));
    expect(canSubmit(tester), isTrue);
    expect(addresses.reverseLookups, 0);
    await tap(tester, submitButton());
    expect(flags.submissions.single['businessAddress'], _manualAddress);
    expect(flags.submissions.single['lat'], _businessPin.latitude);
    expect(
      flags.submissions.single['locationMethod'],
      YellowFlagLocationMethod.manualPin,
    );
  });

  testWidgets(
    'optional suggestion requires pin confirmation and preserves typed description',
    (tester) async {
      addresses.candidates = const [
        YellowFlagAddressCandidate(
          formattedAddress: 'Search provider description',
          latitude: 13.960630,
          longitude: 121.113447,
        ),
      ];
      await openForm(tester);
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isFalse);
      await tap(tester, find.text('Search provider description'));
      expect(map(tester).markers.single.position, _businessPin);
      expect(flags.submissions, isEmpty);
      await tap(tester, confirmButton());
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(flags.submissions.single['lat'], _businessPin.latitude);
    },
  );

  testWidgets('outside-boundary pin cannot be confirmed or submitted', (
    tester,
  ) async {
    await openForm(tester);
    await openMap(tester);
    await selectPin(tester, const LatLng(14.6, 121));
    expect(canConfirm(tester), isFalse);
    expect(
      find.textContaining(
        'outside the official Mataasnakahoy barangay boundaries',
      ),
      findsOneWidget,
    );
    await tap(tester, confirmButton());
    expect(find.byType(GoogleMap), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(canSubmit(tester), isFalse);
    expect(flags.submissions, isEmpty);
  });

  testWidgets(
    'late reverse-geocoding failure never clears a newly typed address',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      addresses.pendingReverse = Completer();
      await openForm(tester, fillAddress: false);
      await tap(tester, find.text('Use current location'), settle: false);
      expect(addresses.reverseLookups, 1);
      expect(canSubmit(tester), isFalse);
      await tester.enterText(addressField(), _manualAddress);
      addresses.pendingReverse!.completeError(
        const YellowFlagAddressSearchException(
          YellowFlagAddressSearchFailure.unavailable,
        ),
      );
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isTrue);
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(flags.submissions.single['lat'], _businessPin.latitude);
    },
  );

  for (final kind in ['ambiguous', 'barangay centroid']) {
    testWidgets('$kind result never establishes a business pin', (
      tester,
    ) async {
      addresses.candidates = kind == 'ambiguous'
          ? [_preciseAddress(), _preciseAddress(number: '117', pin: _movedPin)]
          : [
              YellowFlagAddressCandidate.fromJson({
                'formattedAddress': 'Barangay II, Mataasnakahoy, Batangas',
                'latitude': _businessPin.latitude,
                'longitude': _businessPin.longitude,
                'placeId': 'barangay',
                'providerResultCount': 1,
                'locationType': 'APPROXIMATE',
                'partialMatch': false,
                'resultTypes': ['sublocality_level_1', 'political'],
              }),
            ];
      await openForm(tester, fillAddress: false);
      await resolveAddress(tester);
      expect(find.text(_fallback), findsOneWidget);
      expect(canSubmit(tester), isFalse);
      await openMap(tester);
      expect(map(tester).markers, isEmpty);
      expect(canConfirm(tester), isFalse);
      expect(gps.serviceChecks, 0);
    });
  }

  for (final fillAddress in [false, true]) {
    testWidgets(
      'reverse failure retains GPS and existing input (existing address: $fillAddress)',
      (tester) async {
        gps.permission = LocationPermission.whileInUse;
        addresses.reverseFailure = YellowFlagAddressSearchFailure.unavailable;
        await openForm(tester, fillAddress: fillAddress);
        await tap(tester, find.text('Use current location'));
        expect(find.byType(GoogleMap), findsNothing);
        expect(
          tester.widget<TextFormField>(addressField()).controller!.text,
          fillAddress ? _manualAddress : '',
        );
        expect(
          find.textContaining(
            'GPS coordinates are set, but address lookup is unavailable.',
          ),
          findsOneWidget,
        );
        expect(canSubmit(tester), fillAddress);
        if (!fillAddress) {
          await tester.enterText(addressField(), _manualAddress);
        }
        await tester.pump();
        expect(canSubmit(tester), isTrue);
        await tap(tester, submitButton());
        expect(flags.submissions.single['businessAddress'], _manualAddress);
        expect(flags.submissions.single['lat'], _businessPin.latitude);
        expect(flags.submissions.single['lng'], _businessPin.longitude);
      },
    );
  }

  testWidgets(
    'editing an auto-resolved address invalidates its coordinates until re-resolved',
    (tester) async {
      addresses.candidates = [_preciseAddress()];
      await openForm(tester, fillAddress: false);
      await resolveAddress(tester);
      expect(canSubmit(tester), isTrue);
      addresses.pendingSearch = Completer();
      await tester.enterText(addressField(), '117 Templo Avenue');
      await tester.pump();
      expect(canSubmit(tester), isFalse);
      expect(find.text('Location found'), findsNothing);
      await tester.pump(const Duration(milliseconds: 800));
      expect(canSubmit(tester), isFalse);
      addresses.pendingSearch!.complete([
        _preciseAddress(number: '117', pin: _movedPin),
      ]);
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isTrue);
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], '117 Templo Avenue');
      expect(flags.submissions.single['lat'], _movedPin.latitude);
      expect(flags.submissions.single['lng'], _movedPin.longitude);
    },
  );

  testWidgets(
    'an older address response cannot replace the newer resolved address',
    (tester) async {
      final old = Completer<List<YellowFlagAddressCandidate>>();
      final latest = Completer<List<YellowFlagAddressCandidate>>();
      addresses.onSearch = (address, _) =>
          address.startsWith('115') ? old.future : latest.future;
      await openForm(tester, fillAddress: false);
      await tester.enterText(addressField(), '115 Templo Avenue');
      await tester.pump(const Duration(milliseconds: 800));
      await tester.enterText(addressField(), '117 Templo Avenue');
      await tester.pump(const Duration(milliseconds: 800));
      latest.complete([_preciseAddress(number: '117', pin: _movedPin)]);
      await tester.pumpAndSettle();
      old.complete([_preciseAddress()]);
      await tester.pumpAndSettle();
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], '117 Templo Avenue');
      expect(flags.submissions.single['lat'], _movedPin.latitude);
    },
  );

  testWidgets('manual map selection supersedes a pending address lookup', (
    tester,
  ) async {
    addresses.pendingSearch = Completer();
    await openForm(tester, fillAddress: false);
    await tester.enterText(addressField(), '115 Templo Avenue');
    await tester.pump(const Duration(milliseconds: 800));
    await confirmManualPin(tester);
    addresses.pendingSearch!.complete([_preciseAddress(pin: _movedPin)]);
    await tester.pumpAndSettle();
    await tap(tester, submitButton());
    expect(flags.submissions.single['lat'], _businessPin.latitude);
    expect(flags.submissions.single['businessAddress'], '115 Templo Avenue');
  });

  testWidgets(
    'GPS supersedes pending geocoding and auto-fills its own address',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      addresses.pendingSearch = Completer();
      await openForm(tester, fillAddress: false);
      await tester.enterText(addressField(), '115 Templo Avenue');
      await tester.pump(const Duration(milliseconds: 800));
      await tap(tester, find.text('Use current location'));
      addresses.pendingSearch!.complete([_preciseAddress(pin: _movedPin)]);
      await tester.pumpAndSettle();
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], _gpsAddress);
      expect(flags.submissions.single['lat'], _businessPin.latitude);
    },
  );

  testWidgets(
    'map selection supersedes late GPS without overwriting the manual pin',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      gps.pendingFix = Completer();
      await openForm(tester);
      await tap(tester, find.text('Use current location'), settle: false);
      await openMap(tester);
      await selectPin(tester, _movedPin);
      await tap(tester, confirmButton());
      gps.pendingFix!.complete(
        const InspectionLocationFix(
          latitude: 13.960630,
          longitude: 121.113447,
          accuracy: 10,
        ),
      );
      await tester.pumpAndSettle();
      await tap(tester, submitButton());
      expect(flags.submissions.single['lat'], _movedPin.latitude);
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(addresses.reverseLookups, 0);
    },
  );

  testWidgets('new input supersedes a GPS fix still being acquired', (
    tester,
  ) async {
    gps.permission = LocationPermission.whileInUse;
    gps.pendingFix = Completer();
    addresses.candidates = [_preciseAddress(number: '117', pin: _movedPin)];
    await openForm(tester, fillAddress: false);
    await tap(tester, find.text('Use current location'), settle: false);
    await resolveAddress(tester, address: '117 Templo Avenue');
    gps.pendingFix!.complete(
      const InspectionLocationFix(
        latitude: 13.960630,
        longitude: 121.113447,
        accuracy: 10,
      ),
    );
    await tester.pumpAndSettle();
    await tap(tester, submitButton());
    expect(flags.submissions.single['businessAddress'], '117 Templo Avenue');
    expect(flags.submissions.single['lat'], _movedPin.latitude);
    expect(addresses.reverseLookups, 0);
  });

  testWidgets('late reverse success cannot overwrite newer address input', (
    tester,
  ) async {
    gps.permission = LocationPermission.whileInUse;
    addresses.pendingReverse = Completer();
    await openForm(tester);
    await tap(tester, find.text('Use current location'), settle: false);
    await tester.enterText(addressField(), 'New description beside the school');
    addresses.pendingReverse!.complete(_gpsAddress);
    await tester.pumpAndSettle();
    await tap(tester, submitButton());
    expect(
      flags.submissions.single['businessAddress'],
      'New description beside the school',
    );
    expect(flags.submissions.single['lat'], _businessPin.latitude);
  });

  testWidgets(
    'confirming a map pin supersedes an in-flight GPS address lookup',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      addresses.pendingReverse = Completer();
      await openForm(tester);
      await tap(tester, find.text('Use current location'), settle: false);
      await openMap(tester);
      await selectPin(tester, _movedPin);
      await tap(tester, confirmButton());
      addresses.pendingReverse!.complete(_gpsAddress);
      await tester.pumpAndSettle();
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(flags.submissions.single['lat'], _movedPin.latitude);
      expect(
        flags.submissions.single['locationMethod'],
        YellowFlagLocationMethod.manualPin,
      );
    },
  );

  testWidgets(
    'GPS with no reverse result preserves typed input and its coordinates',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      addresses.reverseAddress = null;
      await openForm(tester);
      await tap(tester, find.text('Use current location'));
      expect(canSubmit(tester), isTrue);
      expect(
        find.textContaining(
          'GPS coordinates are set, but no address was found.',
        ),
        findsOneWidget,
      );
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(flags.submissions.single['lat'], _businessPin.latitude);
      expect(
        flags.submissions.single['locationMethod'],
        YellowFlagLocationMethod.gps,
      );
    },
  );

  for (final method in [
    YellowFlagLocationMethod.address,
    YellowFlagLocationMethod.manualPin,
  ]) {
    testWidgets('restored $method draft keeps its location editing rules', (
      tester,
    ) async {
      flags.drafts = [
        YellowFlagDraft(
          clientSubmissionId: 'saved-report',
          ownerUserId: '9',
          businessName: 'Saved Shop',
          businessAddress: '115 Templo Avenue',
          locationMethod: method,
          lat: _businessPin.latitude,
          lng: _businessPin.longitude,
          barangayId: 2,
          barangayName: 'Barangay II',
          notes: 'Preserve these notes',
          createdAt: '2026-10-17',
          updatedAt: '2026-10-17',
          status: YellowFlagDraftStatus.pendingSync,
        ),
      ];
      await openForm(tester, fillAddress: false);
      await tap(tester, find.text('Review'));
      expect(canSubmit(tester), isTrue);
      expect(addresses.searches, 0);
      await tester.enterText(addressField(), '117 Templo Avenue');
      await tester.pump();
      expect(canSubmit(tester), method == YellowFlagLocationMethod.manualPin);
      addresses.candidates = [_preciseAddress(number: '117', pin: _movedPin)];
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      await tap(tester, submitButton());
      expect(flags.submissions.single['businessAddress'], '117 Templo Avenue');
      expect(
        flags.submissions.single['lat'],
        method == YellowFlagLocationMethod.manualPin
            ? _businessPin.latitude
            : _movedPin.latitude,
      );
      expect(flags.submissions.single['locationMethod'], method);
      expect(
        addresses.searches,
        method == YellowFlagLocationMethod.manualPin ? 0 : 1,
      );
    });
  }

  testWidgets(
    'precise results still require matching municipal and barangay boundaries',
    (tester) async {
      addresses.candidates = [_preciseAddress(pin: const LatLng(14.6, 121))];
      await openForm(tester, fillAddress: false);
      await chooseBarangay(tester, flags.barangays.first);
      await resolveAddress(tester);
      expect(canSubmit(tester), isFalse);
      expect(find.text(_fallback), findsOneWidget);
      addresses.candidates = [_preciseAddress()];
      await chooseBarangay(tester, flags.barangays.last);
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isFalse);
      expect(find.textContaining('not Barangay II-A'), findsOneWidget);
    },
  );

  testWidgets(
    'lookups are debounced and unchanged in-flight requests are reused',
    (tester) async {
      addresses.pendingSearch = Completer();
      await openForm(tester, fillAddress: false);
      for (final input in ['115 Te', '115 Templo', '115 Templo Avenue']) {
        await tester.enterText(addressField(), input);
        await tester.pump(const Duration(milliseconds: 250));
      }
      expect(addresses.searches, 0);
      await tester.pump(const Duration(milliseconds: 700));
      expect(addresses.searches, 1);
      await tester.enterText(addressField(), '115 TEMPLO AVENUE');
      await tester.pump(const Duration(milliseconds: 800));
      expect(addresses.searches, 1);
      addresses.pendingSearch!.complete([_preciseAddress()]);
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isTrue);
      // The inferred barangay and completed result are also cached.
      await tester.enterText(addressField(), '115 Templo Avenue');
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(addresses.searches, 1);
      expect(canSubmit(tester), isTrue);
    },
  );

  testWidgets(
    'offline text-only address needs an alternative and manual pin remains usable',
    (tester) async {
      addresses.searchFailure = YellowFlagAddressSearchFailure.offline;
      await openForm(tester);
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(canSubmit(tester), isFalse);
      expect(find.text(_fallback), findsOneWidget);
      expect(find.textContaining('You are offline.'), findsOneWidget);
      await confirmManualPin(tester);
      await tester.enterText(addressField(), 'Offline description');
      await tester.pump(const Duration(milliseconds: 800));
      expect(canSubmit(tester), isTrue);
      expect(addresses.searches, 1);
      await tap(tester, submitButton());
      expect(
        flags.submissions.single['businessAddress'],
        'Offline description',
      );
      expect(flags.submissions.single['lat'], _businessPin.latitude);
    },
  );

  testWidgets(
    'name, address and barangay validation remain required with a pin',
    (tester) async {
      await openForm(tester, fillAddress: false);
      await confirmManualPin(tester);
      expect(canSubmit(tester), isFalse);
      await tester.enterText(addressField(), _manualAddress);
      await tester.enterText(nameField(), '');
      await tester.pump();
      expect(canSubmit(tester), isFalse);
      await tester.enterText(nameField(), 'Offsite Shop');
      await tester.pump();
      expect(canSubmit(tester), isTrue);
      final dropdown = tester.widget<DropdownButtonFormField<Barangay>>(
        find.byType(DropdownButtonFormField<Barangay>),
      );
      // Invoke the actual dropdown callback using its displayed menu widget.
      final menu = tester.widget<DropdownButton<Barangay>>(
        find.byType(DropdownButton<Barangay>),
      );
      expect(dropdown.enabled, isTrue);
      menu.onChanged!(flags.barangays.last);
      await tester.pump();
      expect(canSubmit(tester), isFalse);
      expect(flags.submissions, isEmpty);
    },
  );

  testWidgets('repeated submit callbacks cannot enqueue duplicate reports', (
    tester,
  ) async {
    flags.pendingSubmission = Completer();
    await openForm(tester);
    await confirmManualPin(tester);
    final submit = tester.widget<ElevatedButton>(submitButton()).onPressed!;
    submit();
    submit();
    await tester.pump();
    expect(flags.submissions, hasLength(1));
    flags.pendingSubmission!.complete(
      const YellowFlagSubmissionResult(
        status: YellowFlagSubmissionStatus.pendingSync,
        clientSubmissionId: 'test-report',
      ),
    );
    await tester.pumpAndSettle();
  });
}
