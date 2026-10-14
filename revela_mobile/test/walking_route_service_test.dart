import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:revela_mobile/service/walking_route_service.dart';

class _FakeWalkingRouteProvider implements WalkingRouteProvider {
  final List<WalkingRouteRequest> requests = [];
  Completer<WalkingRouteResult>? response;
  WalkingRouteResult result = const WalkingRouteResult.failure(
    WalkingRouteFailure.unavailable,
  );

  @override
  Future<WalkingRouteResult> getWalkingRoute(WalkingRouteRequest request) {
    requests.add(request);
    return response?.future ?? Future.value(result);
  }
}

const _route = WalkingRoute(
  points: [LatLng(14.1, 121.1), LatLng(14.11, 121.12)],
  distanceMeters: 1250,
  durationSeconds: 900,
);

void main() {
  test(
    'walking request carries stable task identity and verified endpoints',
    () async {
      final provider = _FakeWalkingRouteProvider()
        ..result = const WalkingRouteResult.success(_route);
      final coordinator = WalkingRouteCoordinator(provider: provider);
      const request = WalkingRouteRequest(
        taskIdentity: 'report:42:cycle:3',
        origin: LatLng(14.1, 121.1),
        destination: LatLng(14.11, 121.12),
      );
      coordinator.selectDestination(request.taskIdentity);

      final result = await coordinator.request(request);

      expect(provider.requests, [request]);
      expect(provider.requests.single.travelMode, 'WALK');
      expect(provider.requests.single.origin, request.origin);
      expect(provider.requests.single.destination, request.destination);
      expect(result.route, _route);
      expect(result.route?.distanceMeters, 1250);
      expect(result.route?.durationSeconds, 900);
      expect(result.route!.toPolyline().points, _route.points);
      expect(result.route!.toPolyline().color, const Color(0xFF1565C0));
    },
  );

  test('a later explicit refresh may request one new route', () async {
    final provider = _FakeWalkingRouteProvider()
      ..result = const WalkingRouteResult.success(_route);
    final coordinator = WalkingRouteCoordinator(provider: provider);
    const request = WalkingRouteRequest(
      taskIdentity: 'report:42:cycle:3',
      origin: LatLng(14.1, 121.1),
      destination: LatLng(14.11, 121.12),
    );
    coordinator.selectDestination(request.taskIdentity);

    await coordinator.request(request);
    await coordinator.request(request);

    expect(provider.requests, hasLength(2));
  });

  test('rapid duplicate requests do not call provider twice', () async {
    final provider = _FakeWalkingRouteProvider()
      ..response = Completer<WalkingRouteResult>();
    final coordinator = WalkingRouteCoordinator(provider: provider);
    const request = WalkingRouteRequest(
      taskIdentity: 'report:42:cycle:3',
      origin: LatLng(14.1, 121.1),
      destination: LatLng(14.11, 121.12),
    );
    coordinator.selectDestination(request.taskIdentity);

    final first = coordinator.request(request);
    final duplicate = await coordinator.request(request);

    expect(provider.requests, hasLength(1));
    expect(duplicate.failure, WalkingRouteFailure.requestInProgress);
    provider.response!.complete(const WalkingRouteResult.success(_route));
    expect((await first).route, _route);
  });

  test('late result for a prior destination is ignored', () async {
    final provider = _FakeWalkingRouteProvider()
      ..response = Completer<WalkingRouteResult>();
    final coordinator = WalkingRouteCoordinator(provider: provider);
    const firstRequest = WalkingRouteRequest(
      taskIdentity: 'report:42:cycle:3',
      origin: LatLng(14.1, 121.1),
      destination: LatLng(14.11, 121.12),
    );
    coordinator.selectDestination(firstRequest.taskIdentity);

    final pending = coordinator.request(firstRequest);
    coordinator.selectDestination('report:43:cycle:1');
    provider.response!.complete(const WalkingRouteResult.success(_route));

    final result = await pending;
    expect(result.route, isNull);
    expect(result.failure, WalkingRouteFailure.stale);
  });

  test(
    'invalid route geometry is not returned as a successful route',
    () async {
      final provider = _FakeWalkingRouteProvider()
        ..result = const WalkingRouteResult.success(
          WalkingRoute(points: [LatLng(14, 121), LatLng(double.nan, 121)]),
        );
      final coordinator = WalkingRouteCoordinator(provider: provider)
        ..selectDestination('report:42:cycle:3');

      final result = await coordinator.request(
        const WalkingRouteRequest(
          taskIdentity: 'report:42:cycle:3',
          origin: LatLng(14.1, 121.1),
          destination: LatLng(14.11, 121.12),
        ),
      );

      expect(result.route, isNull);
      expect(result.failure, WalkingRouteFailure.noRoute);
    },
  );

  test('unconfigured default provider does not invent a route', () async {
    final coordinator = WalkingRouteCoordinator(
      provider: const UnconfiguredWalkingRouteProvider(),
    )..selectDestination('report:42:cycle:3');

    final result = await coordinator.request(
      const WalkingRouteRequest(
        taskIdentity: 'report:42:cycle:3',
        origin: LatLng(14.1, 121.1),
        destination: LatLng(14.11, 121.12),
      ),
    );

    expect(result.route, isNull);
    expect(result.failure, WalkingRouteFailure.providerNotConfigured);
  });

  test(
    'provider exceptions produce an unavailable result without a route',
    () async {
      final provider = _ThrowingWalkingRouteProvider();
      final coordinator = WalkingRouteCoordinator(provider: provider)
        ..selectDestination('report:42:cycle:3');

      final result = await coordinator.request(
        const WalkingRouteRequest(
          taskIdentity: 'report:42:cycle:3',
          origin: LatLng(14.1, 121.1),
          destination: LatLng(14.11, 121.12),
        ),
      );

      expect(result.route, isNull);
      expect(result.failure, WalkingRouteFailure.unavailable);
    },
  );
}

class _ThrowingWalkingRouteProvider implements WalkingRouteProvider {
  @override
  Future<WalkingRouteResult> getWalkingRoute(WalkingRouteRequest request) {
    throw Exception('mock provider failure');
  }
}
