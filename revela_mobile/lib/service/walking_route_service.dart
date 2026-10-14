import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

enum WalkingRouteFailure {
  providerNotConfigured,
  offline,
  unavailable,
  noRoute,
  requestInProgress,
  stale,
}

class WalkingRouteRequest {
  const WalkingRouteRequest({
    required this.taskIdentity,
    required this.origin,
    required this.destination,
  });

  final String taskIdentity;
  final LatLng origin;
  final LatLng destination;

  String get travelMode => 'WALK';
}

class WalkingRoute {
  const WalkingRoute({
    required this.points,
    this.distanceMeters,
    this.durationSeconds,
  });

  final List<LatLng> points;
  final int? distanceMeters;
  final double? durationSeconds;

  Polyline toPolyline() => Polyline(
    polylineId: const PolylineId('walking_route'),
    points: points,
    color: const Color(0xFF1565C0),
    width: 6,
    zIndex: 10,
    jointType: JointType.round,
    startCap: Cap.roundCap,
    endCap: Cap.roundCap,
  );
}

class WalkingRouteResult {
  const WalkingRouteResult._({this.route, this.failure});

  const WalkingRouteResult.success(WalkingRoute route) : this._(route: route);

  const WalkingRouteResult.failure(WalkingRouteFailure failure)
    : this._(failure: failure);

  final WalkingRoute? route;
  final WalkingRouteFailure? failure;
}

abstract interface class WalkingRouteProvider {
  Future<WalkingRouteResult> getWalkingRoute(WalkingRouteRequest request);
}

/// Prevents accidental billable requests until a routing provider is approved.
class UnconfiguredWalkingRouteProvider implements WalkingRouteProvider {
  const UnconfiguredWalkingRouteProvider();

  @override
  Future<WalkingRouteResult> getWalkingRoute(WalkingRouteRequest request) =>
      Future.value(
        const WalkingRouteResult.failure(
          WalkingRouteFailure.providerNotConfigured,
        ),
      );
}

class WalkingRouteCoordinator {
  WalkingRouteCoordinator({required WalkingRouteProvider provider})
    : _provider = provider;

  final WalkingRouteProvider _provider;
  String? _selectedTaskIdentity;
  int _selectionGeneration = 0;
  bool _requestInProgress = false;

  void selectDestination(String taskIdentity) {
    if (_selectedTaskIdentity == taskIdentity) return;
    _selectedTaskIdentity = taskIdentity;
    _selectionGeneration++;
  }

  Future<WalkingRouteResult> request(WalkingRouteRequest request) async {
    if (request.taskIdentity != _selectedTaskIdentity) {
      return const WalkingRouteResult.failure(WalkingRouteFailure.stale);
    }
    if (_requestInProgress) {
      return const WalkingRouteResult.failure(
        WalkingRouteFailure.requestInProgress,
      );
    }

    _requestInProgress = true;
    final generation = _selectionGeneration;
    try {
      final result = await _provider.getWalkingRoute(request);
      if (generation != _selectionGeneration ||
          request.taskIdentity != _selectedTaskIdentity) {
        return const WalkingRouteResult.failure(WalkingRouteFailure.stale);
      }

      final route = result.route;
      if (route != null &&
          (route.points.length < 2 ||
              route.points.any(
                (point) =>
                    !point.latitude.isFinite ||
                    !point.longitude.isFinite ||
                    point.latitude < -90 ||
                    point.latitude > 90 ||
                    point.longitude < -180 ||
                    point.longitude > 180,
              ) ||
              (route.distanceMeters != null && route.distanceMeters! < 0) ||
              (route.durationSeconds != null &&
                  (!route.durationSeconds!.isFinite ||
                      route.durationSeconds! < 0)))) {
        return const WalkingRouteResult.failure(WalkingRouteFailure.noRoute);
      }
      return result;
    } on Exception catch (error) {
      debugPrint('Walking route provider failed: $error');
      return const WalkingRouteResult.failure(WalkingRouteFailure.unavailable);
    } finally {
      _requestInProgress = false;
    }
  }
}
