import 'dart:async';

import 'package:geolocator/geolocator.dart';

enum InspectionLocationIssue {
  none,
  locationServicesDisabled,
  permissionDenied,
  permissionDeniedForever,
  timedOut,
  unavailable,
  inaccurate,
}

class InspectionLocationFix {
  const InspectionLocationFix({
    required this.latitude,
    required this.longitude,
    required this.accuracy,
  });

  final double latitude;
  final double longitude;
  final double accuracy;
}

class InspectionLocationResult {
  const InspectionLocationResult._(this.fix, this.issue);

  const InspectionLocationResult.success(InspectionLocationFix fix)
    : this._(fix, InspectionLocationIssue.none);

  const InspectionLocationResult.failure(InspectionLocationIssue issue)
    : this._(null, issue);

  final InspectionLocationFix? fix;
  final InspectionLocationIssue issue;

  bool get hasFix => fix != null;

  String get message => switch (issue) {
    InspectionLocationIssue.none => 'GPS location acquired.',
    InspectionLocationIssue.locationServicesDisabled =>
      'Device Location Services are off. Turn them on and retry.',
    InspectionLocationIssue.permissionDenied =>
      'Location permission was denied. Allow location access and retry.',
    InspectionLocationIssue.permissionDeniedForever =>
      'Location permission is blocked. Enable it in app settings.',
    InspectionLocationIssue.timedOut =>
      'GPS did not get a fix in time. Move to an open area and retry.',
    InspectionLocationIssue.unavailable =>
      'A GPS location is unavailable right now. Retry when ready.',
    InspectionLocationIssue.inaccurate =>
      'GPS accuracy is too low for a verified location. Move to an open area and retry.',
  };

  bool get canRetry =>
      issue == InspectionLocationIssue.timedOut ||
      issue == InspectionLocationIssue.unavailable ||
      issue == InspectionLocationIssue.inaccurate ||
      issue == InspectionLocationIssue.permissionDenied;

  bool get canOpenSettings =>
      issue == InspectionLocationIssue.locationServicesDisabled ||
      issue == InspectionLocationIssue.permissionDeniedForever;
}

abstract interface class InspectionLocationPlatform {
  Future<bool> isLocationServiceEnabled();
  Future<LocationPermission> checkPermission();
  Future<LocationPermission> requestPermission();
  Future<InspectionLocationFix> getCurrentFix(Duration timeout);
  Future<bool> openLocationSettings();
  Future<bool> openAppSettings();
}

class _GeolocatorInspectionLocationPlatform
    implements InspectionLocationPlatform {
  const _GeolocatorInspectionLocationPlatform();

  @override
  Future<bool> isLocationServiceEnabled() =>
      Geolocator.isLocationServiceEnabled();

  @override
  Future<LocationPermission> checkPermission() => Geolocator.checkPermission();

  @override
  Future<LocationPermission> requestPermission() =>
      Geolocator.requestPermission();

  @override
  Future<InspectionLocationFix> getCurrentFix(Duration timeout) async {
    final position = await Geolocator.getCurrentPosition(
      locationSettings: LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: timeout,
      ),
    );
    return InspectionLocationFix(
      latitude: position.latitude,
      longitude: position.longitude,
      accuracy: position.accuracy,
    );
  }

  @override
  Future<bool> openLocationSettings() => Geolocator.openLocationSettings();

  @override
  Future<bool> openAppSettings() => Geolocator.openAppSettings();
}

class InspectionLocationService {
  InspectionLocationService({
    InspectionLocationPlatform? platform,
    this.timeout = const Duration(seconds: 15),
    this.maximumAccuracyMeters = 100,
  }) : _platform = platform ?? const _GeolocatorInspectionLocationPlatform();

  final InspectionLocationPlatform _platform;
  final Duration timeout;
  final double maximumAccuracyMeters;

  Future<InspectionLocationResult> getCurrentLocation() async {
    try {
      if (!await _platform.isLocationServiceEnabled()) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.locationServicesDisabled,
        );
      }

      var permission = await _platform.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await _platform.requestPermission();
      }
      if (permission == LocationPermission.deniedForever) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.permissionDeniedForever,
        );
      }
      if (permission == LocationPermission.denied) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.permissionDenied,
        );
      }

      final fix = await _platform.getCurrentFix(timeout);
      if (fix.accuracy.isFinite && fix.accuracy > maximumAccuracyMeters) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.inaccurate,
        );
      }
      if (!_validCoordinates(fix)) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.unavailable,
        );
      }
      if (!fix.accuracy.isFinite || fix.accuracy < 0) {
        return const InspectionLocationResult.failure(
          InspectionLocationIssue.inaccurate,
        );
      }
      return InspectionLocationResult.success(fix);
    } on TimeoutException {
      return const InspectionLocationResult.failure(
        InspectionLocationIssue.timedOut,
      );
    } on LocationServiceDisabledException {
      return const InspectionLocationResult.failure(
        InspectionLocationIssue.locationServicesDisabled,
      );
    } on PermissionDeniedException {
      return const InspectionLocationResult.failure(
        InspectionLocationIssue.permissionDenied,
      );
    } catch (_) {
      return const InspectionLocationResult.failure(
        InspectionLocationIssue.unavailable,
      );
    }
  }

  Future<bool> openSettings(InspectionLocationIssue issue) {
    if (issue == InspectionLocationIssue.locationServicesDisabled) {
      return _platform.openLocationSettings();
    }
    if (issue == InspectionLocationIssue.permissionDeniedForever) {
      return _platform.openAppSettings();
    }
    return Future.value(false);
  }

  bool _validCoordinates(InspectionLocationFix fix) =>
      fix.latitude.isFinite &&
      fix.longitude.isFinite &&
      fix.latitude >= -90 &&
      fix.latitude <= 90 &&
      fix.longitude >= -180 &&
      fix.longitude <= 180;
}
