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
  Completer<YellowFlagSubmissionResult>? pendingSubmission;
  final barangays = const [
    Barangay(id: 2, name: 'Barangay II'),
    Barangay(id: 3, name: 'Barangay II-A'),
  ];

  @override
  Future<List<Barangay>> fetchBarangays() async => barangays;

  @override
  Future<List<YellowFlagDraft>> getMyYellowFlagDrafts() async => [];

  @override
  Future<YellowFlagSubmissionResult> submitYellowFlag({
    required String businessName,
    required String businessAddress,
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
  int searches = 0;
  int reverseLookups = 0;

  @override
  Future<List<YellowFlagAddressCandidate>> search({
    required String streetAddress,
    String? barangay,
  }) async {
    searches++;
    return pendingSearch?.future ?? candidates;
  }

  @override
  Future<String?> reverseGeocode({
    required double latitude,
    required double longitude,
  }) async {
    reverseLookups++;
    return pendingReverse?.future;
  }
}

class _Gps implements InspectionLocationPlatform {
  LocationPermission permission = LocationPermission.deniedForever;
  int serviceChecks = 0;
  int permissionRequests = 0;
  int fixRequests = 0;

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
    return const InspectionLocationFix(
      latitude: 13.960630,
      longitude: 121.113447,
      accuracy: 10,
    );
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

  Future<void> tap(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    await tester.pumpAndSettle();
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

  testWidgets('typed address alone shows guidance and cannot submit', (
    tester,
  ) async {
    await openForm(tester);
    expect(
      find.text(
        'Choose the business location on the map or use your current location.',
      ),
      findsOneWidget,
    );
    expect(canSubmit(tester), isFalse);
    await tap(tester, submitButton());
    expect(flags.submissions, isEmpty);
    expect(gps.serviceChecks, 0);
  });

  testWidgets(
    'address edits preserve the pin and optional search does not gate submit',
    (tester) async {
      await openForm(tester);
      await confirmManualPin(tester);
      addresses.pendingSearch = Completer();
      await tester.enterText(
        addressField(),
        'Unlisted alley beside the old mango tree',
      );
      await tester.pump(const Duration(milliseconds: 800));
      expect(canSubmit(tester), isTrue);
      await tap(tester, submitButton());
      expect(
        flags.submissions.single['businessAddress'],
        'Unlisted alley beside the old mango tree',
      );
      expect(flags.submissions.single['lat'], _businessPin.latitude);
      expect(flags.submissions.single['lng'], _businessPin.longitude);
      addresses.pendingSearch!.complete([]);
      await tester.pumpAndSettle();
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

  testWidgets(
    'current location is reviewed and submits the confirmed business pin',
    (tester) async {
      gps.permission = LocationPermission.whileInUse;
      await openForm(tester);
      await tap(tester, find.text('Use current location'));
      expect(map(tester).markers.single.position, _businessPin);
      expect(flags.submissions, isEmpty);
      await selectPin(tester, _movedPin);
      await tap(tester, confirmButton());
      expect(canSubmit(tester), isTrue);
      await tap(tester, submitButton());
      expect(gps.fixRequests, 1);
      expect(flags.submissions.single['businessAddress'], _manualAddress);
      expect(flags.submissions.single['lat'], _movedPin.latitude);
      expect(flags.submissions.single['lng'], _movedPin.longitude);
      expect(addresses.reverseLookups, 0);
    },
  );

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
      await tap(tester, find.text('Use current location'));
      await tap(tester, confirmButton());
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
