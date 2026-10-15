import 'dart:async';
import 'dart:collection';

import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:revela_mobile/service/inspection_location_service.dart';

class _FakeLocationPlatform implements InspectionLocationPlatform {
  bool serviceEnabled = true;
  LocationPermission permission = LocationPermission.whileInUse;
  LocationPermission requestedPermission = LocationPermission.whileInUse;
  final Queue<Future<InspectionLocationFix> Function()> fixes = Queue();
  int fixRequests = 0;
  Duration? requestedTimeout;
  int appSettingsOpens = 0;
  int locationSettingsOpens = 0;

  @override
  Future<bool> isLocationServiceEnabled() async => serviceEnabled;

  @override
  Future<LocationPermission> checkPermission() async => permission;

  @override
  Future<LocationPermission> requestPermission() async => requestedPermission;

  @override
  Future<InspectionLocationFix> getCurrentFix(Duration timeout) {
    fixRequests++;
    requestedTimeout = timeout;
    if (fixes.isEmpty) {
      return Future.error(StateError('No fake fix configured'));
    }
    return fixes.removeFirst()();
  }

  @override
  Future<bool> openAppSettings() async {
    appSettingsOpens++;
    return true;
  }

  @override
  Future<bool> openLocationSettings() async {
    locationSettingsOpens++;
    return true;
  }
}

const _goodFix = InspectionLocationFix(
  latitude: 14.123,
  longitude: 121.456,
  accuracy: 12,
);

void main() {
  test(
    'obtains a valid native GPS fix without requiring network access',
    () async {
      final platform = _FakeLocationPlatform()..fixes.add(() async => _goodFix);
      final service = InspectionLocationService(platform: platform);

      final result = await service.getCurrentLocation();

      expect(result.hasFix, isTrue);
      expect(result.fix?.latitude, _goodFix.latitude);
      expect(result.fix?.longitude, _goodFix.longitude);
      expect(platform.fixRequests, 1);
      expect(platform.requestedTimeout, const Duration(seconds: 15));
    },
  );

  test('requests permission once and reports denied permission', () async {
    final platform = _FakeLocationPlatform()
      ..permission = LocationPermission.denied
      ..requestedPermission = LocationPermission.denied;
    final service = InspectionLocationService(platform: platform);

    final result = await service.getCurrentLocation();

    expect(result.issue, InspectionLocationIssue.permissionDenied);
    expect(result.canRetry, isTrue);
    expect(platform.fixRequests, 0);
  });

  test('permanently denied permission points to app settings', () async {
    final platform = _FakeLocationPlatform()
      ..permission = LocationPermission.deniedForever;
    final service = InspectionLocationService(platform: platform);

    final result = await service.getCurrentLocation();
    final opened = await service.openSettings(result.issue);

    expect(result.issue, InspectionLocationIssue.permissionDeniedForever);
    expect(result.canOpenSettings, isTrue);
    expect(opened, isTrue);
    expect(platform.appSettingsOpens, 1);
    expect(platform.fixRequests, 0);
  });

  test('disabled device location points to location settings', () async {
    final platform = _FakeLocationPlatform()..serviceEnabled = false;
    final service = InspectionLocationService(platform: platform);

    final result = await service.getCurrentLocation();
    final opened = await service.openSettings(result.issue);

    expect(result.issue, InspectionLocationIssue.locationServicesDisabled);
    expect(result.canOpenSettings, isTrue);
    expect(opened, isTrue);
    expect(platform.locationSettingsOpens, 1);
    expect(platform.fixRequests, 0);
  });

  test('GPS timeout is distinguished from general unavailability', () async {
    final platform = _FakeLocationPlatform()
      ..fixes.add(() => Future.error(TimeoutException('GPS timeout')));
    final service = InspectionLocationService(platform: platform);

    final result = await service.getCurrentLocation();

    expect(result.issue, InspectionLocationIssue.timedOut);
    expect(result.canRetry, isTrue);
  });

  test('retry after timeout obtains a fresh valid fix', () async {
    final platform = _FakeLocationPlatform()
      ..fixes.add(() => Future.error(TimeoutException('GPS timeout')))
      ..fixes.add(() async => _goodFix);
    final service = InspectionLocationService(platform: platform);

    final first = await service.getCurrentLocation();
    final retry = await service.getCurrentLocation();

    expect(first.issue, InspectionLocationIssue.timedOut);
    expect(retry.hasFix, isTrue);
    expect(platform.fixRequests, 2);
  });

  test(
    'unavailable and inaccurate fixes are not exposed as coordinates',
    () async {
      final unavailablePlatform = _FakeLocationPlatform()
        ..fixes.add(
          () async => const InspectionLocationFix(
            latitude: double.nan,
            longitude: 121,
            accuracy: 10,
          ),
        );
      final inaccuratePlatform = _FakeLocationPlatform()
        ..fixes.add(
          () async => const InspectionLocationFix(
            latitude: 14,
            longitude: 121,
            accuracy: 150,
          ),
        );

      final unavailable = await InspectionLocationService(
        platform: unavailablePlatform,
      ).getCurrentLocation();
      final inaccurate = await InspectionLocationService(
        platform: inaccuratePlatform,
      ).getCurrentLocation();

      expect(unavailable.issue, InspectionLocationIssue.unavailable);
      expect(unavailable.fix, isNull);
      expect(inaccurate.issue, InspectionLocationIssue.inaccurate);
      expect(inaccurate.fix, isNull);
    },
  );

  test('rejected GPS accuracy threshold is configurable', () async {
    final platform = _FakeLocationPlatform()
      ..fixes.add(
        () async => const InspectionLocationFix(
          latitude: 14,
          longitude: 121,
          accuracy: 55,
        ),
      );

    final result = await InspectionLocationService(
      platform: platform,
      maximumAccuracyMeters: 60,
    ).getCurrentLocation();

    expect(result.hasFix, isTrue);
  });
}
