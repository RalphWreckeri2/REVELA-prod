import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shimmer/shimmer.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:geolocator/geolocator.dart';

import '../component/inspection_card.dart';
import '../component/inspection_modal.dart';
import '../component/yellow_flag_location_picker.dart';

import '../service/assignment_notifications.dart';
import '../service/flag_service.dart';
import '../service/boundary_service.dart';
import '../service/inspection_location_service.dart';
import '../service/connectivity_service.dart';
import '../service/offline_inspection_storage.dart';

import '../service/inspection_service.dart';
import '../service/auth_service.dart';
import '../service/walking_route_service.dart';
import '../service/yellow_flag_candidates.dart';
import '../service/yellow_flag_address_search.dart';
import '../theme/app_theme.dart';
import '../theme/map_styles.dart';
import 'street_view_screen.dart';
import 'package:showcaseview/showcaseview.dart';
import 'main_layout.dart';

class HomePage extends StatefulWidget {
  final ValueChanged<bool>? onDrawerToggled;
  final bool isVisible;
  final WalkingRouteProvider? walkingRouteProvider;

  const HomePage({
    super.key,
    this.onDrawerToggled,
    this.isVisible = true,
    this.walkingRouteProvider,
  });

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  static const Set<String> _activeStatuses = {'Assigned', 'Reassigned'};
  static const ClusterManagerId _flagClusterManagerId = ClusterManagerId(
    'inspection_flags',
  );

  GoogleMapController? _mapController;
  final InspectionLocationService _locationService =
      InspectionLocationService();
  late final WalkingRouteCoordinator _walkingRouteCoordinator;
  InspectionTask? _routeTask;
  WalkingRoute? _walkingRoute;
  String? _routeMessage;
  bool _isRouteLoading = false;
  int _routeUiGeneration = 0;
  StreamSubscription<Position>? _pedestrianPositionSubscription;
  LatLng? _pedestrianPosition;
  BitmapDescriptor? _pedestrianMarker;
  bool _hasAutoFramedTasks = false;
  bool _isDockerExpanded = false;
  bool _isFirstLoad = true;
  String _sortBy = 'newest'; // 'newest' or 'oldest'
  String _dockerTab = 'tasks';
  bool _hasLocationPermission = false;
  bool _isAppForeground = true;
  bool _isLegendOpen = false;
  BitmapDescriptor? _blackMarker;
  BitmapDescriptor? _municipalMarker;

  Future<void> _initMarkers() async {
    final PictureRecorder pictureRecorder = PictureRecorder();
    final Canvas canvas = Canvas(pictureRecorder);
    final Paint paint = Paint()..color = Colors.black;
    final Path path = Path()
      ..moveTo(24, 48)
      ..lineTo(34, 30)
      ..arcToPoint(
        const Offset(14, 30),
        radius: const Radius.circular(12),
        clockwise: false,
      )
      ..lineTo(24, 48)
      ..close();
    canvas.drawPath(path, paint);
    canvas.drawCircle(const Offset(24, 20), 6, Paint()..color = Colors.white);

    final img = await pictureRecorder.endRecording().toImage(48, 48);
    final data = await img.toByteData(format: ImageByteFormat.png);
    if (data != null) {
      _blackMarker = BitmapDescriptor.bytes(data.buffer.asUint8List());
    }

    final pedestrianRecorder = PictureRecorder();
    final pedestrianCanvas = Canvas(pedestrianRecorder);
    pedestrianCanvas.drawCircle(
      const Offset(32, 32),
      30,
      Paint()..color = AppColors.darkGreen,
    );
    final pedestrianPainter = TextPainter(
      text: TextSpan(
        text: String.fromCharCode(Icons.directions_walk_rounded.codePoint),
        style: TextStyle(
          fontSize: 34,
          fontFamily: Icons.directions_walk_rounded.fontFamily,
          package: Icons.directions_walk_rounded.fontPackage,
          color: Colors.white,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    pedestrianPainter.paint(
      pedestrianCanvas,
      Offset(
        (64 - pedestrianPainter.width) / 2,
        (64 - pedestrianPainter.height) / 2,
      ),
    );
    final pedestrianImage = await pedestrianRecorder.endRecording().toImage(
      64,
      64,
    );
    final pedestrianData = await pedestrianImage.toByteData(
      format: ImageByteFormat.png,
    );
    if (pedestrianData != null) {
      _pedestrianMarker = BitmapDescriptor.bytes(
        pedestrianData.buffer.asUint8List(),
      );
    }

    try {
      final PictureRecorder muniRecorder = PictureRecorder();
      final Canvas muniCanvas = Canvas(muniRecorder);
      final Paint muniPaint = Paint()..color = Colors.blue.shade800;
      final Paint whitePaint = Paint()..color = Colors.white;

      // Draw outer white border and inner blue circle
      muniCanvas.drawCircle(const Offset(24, 24), 22, whitePaint);
      muniCanvas.drawCircle(const Offset(24, 24), 19, muniPaint);

      // Draw building icon in the center
      final TextPainter textPainter = TextPainter(
        textDirection: TextDirection.ltr,
      );
      textPainter.text = TextSpan(
        text: String.fromCharCode(Icons.account_balance.codePoint),
        style: TextStyle(
          fontSize: 22.0,
          fontFamily: Icons.account_balance.fontFamily,
          package: Icons.account_balance.fontPackage,
          color: Colors.white,
        ),
      );
      textPainter.layout();
      textPainter.paint(muniCanvas, const Offset(13, 13));

      final muniImg = await muniRecorder.endRecording().toImage(48, 48);
      final muniData = await muniImg.toByteData(format: ImageByteFormat.png);
      if (muniData != null) {
        _municipalMarker = BitmapDescriptor.bytes(
          muniData.buffer.asUint8List(),
        );
      }
    } catch (e) {
      debugPrint('Error loading municipal icon for map: $e');
    }

    if (mounted) setState(() {});
  }

  Timer? _pollTimer;
  bool _assignmentNotifyPrimed = false;
  bool _isDrawerOpen = false;

  // ── Google Map ─────────────────────────────────────────────────────────────

  MapType _currentMapType = MapType.normal;
  bool _is3DView = false;
  bool _streetViewPickMode = false;
  CameraPosition? _currentCameraPosition;
  static const CameraPosition _initialCamera = CameraPosition(
    target: LatLng(13.9667, 121.1167),
    zoom: 12,
  );

  Future<void> _openStreetView(LatLng position) async {
    if (!mounted) return;
    if (_streetViewPickMode) {
      setState(() => _streetViewPickMode = false);
    }
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => StreetViewScreen(position: position),
      ),
    );
  }

  void _beginStreetViewLocationPick() {
    setState(() => _streetViewPickMode = true);
  }

  // ── Real data ──────────────────────────────────────────────────────────────
  List<InspectionTask> _tasks = [];
  bool _loadingTasks = true;
  String? _taskError;

  /// Yellow flags submitted by this inspector (shown as extra map markers).
  final InMemoryYellowFlagSnapshot _submittedFlags =
      InMemoryYellowFlagSnapshot();
  int _myFlagsFetchGeneration = 0;
  bool _isYellowPickerOpen = false;
  bool _isYellowSelectionResolving = false;

  List<MyFlag> get _myFlags => _submittedFlags.flags;

  List<InspectionTask> get _sortedTasks {
    final sorted = List<InspectionTask>.from(_tasks);
    sorted.sort((a, b) {
      final dtA = DateTime.tryParse(a.irTimestamp) ?? DateTime(0);
      final dtB = DateTime.tryParse(b.irTimestamp) ?? DateTime(0);
      return _sortBy == 'newest' ? dtB.compareTo(dtA) : dtA.compareTo(dtB);
    });
    return sorted;
  }

  @override
  void initState() {
    super.initState();
    _walkingRouteCoordinator = WalkingRouteCoordinator(
      provider:
          widget.walkingRouteProvider ??
          const UnconfiguredWalkingRouteProvider(),
    );
    WidgetsBinding.instance.addObserver(this);
    _initMarkers();
    _primePermissionsAndFetch();
    _pollTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) {
        _fetchTasks(silent: true);
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _stopPedestrianTracking();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant HomePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.isVisible && !widget.isVisible) {
      _stopPedestrianTracking();
      _routeUiGeneration++;
      _walkingRouteCoordinator.selectDestination('');
      _routeTask = null;
      _walkingRoute = null;
      _routeMessage = null;
      _isRouteLoading = false;
    } else if (!oldWidget.isVisible && widget.isVisible) {
      _startPedestrianTracking();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _resumeLocationTracking();
      _fetchTasks(silent: true);
    } else if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _stopPedestrianTracking();
      if (mounted) {
        setState(() => _isAppForeground = false);
      } else {
        _isAppForeground = false;
      }
    }
  }

  Future<void> _resumeLocationTracking() async {
    if (mounted && !_isAppForeground) {
      setState(() => _isAppForeground = true);
    }
    await _refreshLocationAvailability();
  }

  Future<void> _primePermissionsAndFetch() async {
    await Future.wait([_fetchTasks(), _fetchMyFlags()]);
  }

  Future<void> _fetchTasks({bool silent = false}) async {
    final previous = List<InspectionTask>.from(_tasks);
    if (!silent && mounted) {
      setState(() {
        _loadingTasks = true;
        _taskError = null;
      });
    }
    try {
      final tasks = await InspectionService().getMyTasks();
      final currentTasks = tasks
          .where((t) => _activeStatuses.contains(t.verificationStatus))
          .toList();

      if (_assignmentNotifyPrimed) {
        await AssignmentNotifications.notifyNewAssignments(
          previous: previous,
          next: currentTasks,
        );
        await AssignmentNotifications.notifyApproachingDeadlines(currentTasks);
      } else {
        _assignmentNotifyPrimed = true;
      }

      if (mounted) {
        setState(() {
          _tasks = currentTasks;
          _loadingTasks = false;
        });
        _syncMapToTasks();
      }
    } catch (e) {
      debugPrint('_fetchTasks: $e');
      if (mounted) {
        setState(() {
          _taskError =
              'Unable to connect to the server. Please check your internet connection and try again.';
          _loadingTasks = false;
        });
      }
    }
    // Silently refresh own-reported flags alongside every task refresh.
    _fetchMyFlags();
  }

  Future<void> _fetchMyFlags() async {
    final generation = ++_myFlagsFetchGeneration;
    String? userId;
    try {
      userId = await AuthService().getAuthenticatedUserId();
    } catch (error) {
      debugPrint('Could not identify account for submitted flags: $error');
      if (mounted) {
        setState(() => _submittedFlags.selectAccount(null));
      }
      return;
    }
    if (!mounted) return;
    if (userId == null || userId.isEmpty) {
      if (_submittedFlags.accountId != null) {
        setState(() => _submittedFlags.selectAccount(null));
      }
      return;
    }
    final accountId = userId;
    if (_submittedFlags.accountId != accountId) {
      setState(() => _submittedFlags.selectAccount(accountId));
    }

    try {
      final flags = await FlagService().fetchMyYellowFlags();
      final currentUserId = await AuthService().getAuthenticatedUserId();
      if (!mounted ||
          generation != _myFlagsFetchGeneration ||
          currentUserId != accountId) {
        return;
      }
      setState(
        () => _submittedFlags.replaceAfterSuccessfulRefresh(accountId, flags),
      );
    } catch (e) {
      debugPrint('_fetchMyFlags: $e');
      _submittedFlags.retainAfterFailedRefresh(accountId);
    }
  }

  void _syncMapToTasks() {
    if (_mapController == null || _hasAutoFramedTasks) return;
    final withCoords = _tasks
        .where((t) => t.latitude != null && t.longitude != null)
        .toList();
    if (withCoords.isEmpty) return;
    _hasAutoFramedTasks = true;
    if (withCoords.length == 1) {
      final t = withCoords.first;
      _mapController!.animateCamera(
        CameraUpdate.newLatLngZoom(LatLng(t.latitude!, t.longitude!), 15),
      );
      return;
    }
    double minLat = withCoords.first.latitude!, maxLat = minLat;
    double minLng = withCoords.first.longitude!, maxLng = minLng;
    for (final t in withCoords) {
      minLat = minLat < t.latitude! ? minLat : t.latitude!;
      maxLat = maxLat > t.latitude! ? maxLat : t.latitude!;
      minLng = minLng < t.longitude! ? minLng : t.longitude!;
      maxLng = maxLng > t.longitude! ? maxLng : t.longitude!;
    }
    if ((maxLat - minLat).abs() < 0.0005) {
      minLat -= 0.002;
      maxLat += 0.002;
    }
    if ((maxLng - minLng).abs() < 0.0005) {
      minLng -= 0.002;
      maxLng += 0.002;
    }
    _mapController!.animateCamera(
      CameraUpdate.newLatLngBounds(
        LatLngBounds(
          southwest: LatLng(minLat, minLng),
          northeast: LatLng(maxLat, maxLng),
        ),
        80,
      ),
    );
  }

  Set<Marker> _buildFlagMarkers() {
    final markers = <Marker>{};

    final pedestrianPosition = _pedestrianPosition;
    if (pedestrianPosition != null) {
      markers.add(
        Marker(
          markerId: const MarkerId('inspector_pedestrian_location'),
          position: pedestrianPosition,
          infoWindow: const InfoWindow(title: 'Your current location'),
          icon:
              _pedestrianMarker ??
              BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueAzure),
          zIndexInt: 100,
        ),
      );
    }

    // ── Municipality Hall Marker ─────────────────────────────────────────────
    markers.add(
      Marker(
        markerId: const MarkerId('mataasnakahoy_municipal_hall'),
        position: const LatLng(13.960416, 121.114547),
        infoWindow: const InfoWindow(
          title: 'Mataasnakahoy Municipal Hall',
          snippet: 'Center of operations',
        ),
        icon:
            _municipalMarker ??
            BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueAzure),
      ),
    );

    // ── Assignment-task markers (pinned by the system) ──────────────────
    for (final t in _tasks) {
      if (!hasValidCoordinates(t.latitude, t.longitude)) continue;
      final icon = t.flagColor == 'Black' && _blackMarker != null
          ? _blackMarker!
          : BitmapDescriptor.defaultMarkerWithHue(switch (t.flagColor) {
              'Red' => BitmapDescriptor.hueRed,
              'Yellow' => BitmapDescriptor.hueYellow,
              'Orange' =>
                15.0, // deep orange hue — distinct from hueYellow (60) and hueOrange (30)
              'Purple' => BitmapDescriptor.hueViolet, // 270.0 degrees - purple
              _ => BitmapDescriptor.hueGreen,
            });
      markers.add(
        Marker(
          markerId: MarkerId('flag_${t.logID}'),
          position: LatLng(t.latitude!, t.longitude!),
          clusterManagerId: _flagClusterManagerId,
          infoWindow: InfoWindow(
            title: t.detectedName,
            snippet: '${t.barangayName} · ${t.flagColor}',
          ),
          icon: icon,
          onTap: () => t.flagColor == 'Yellow'
              ? _onYellowTaskMarkerTap(t)
              : _onTaskTap(t),
        ),
      );
    }

    // ── Inspector-reported yellow flag markers ──────────────────────────
    // These are flags this inspector submitted via the "Flag Business" button.
    // Show a "You flagged" snippet so the inspector knows it's their own submission.
    for (final f in _myFlags) {
      // Skip if this flag is already shown as an assigned task.
      if (_tasks.any((t) => t.logID == f.logID)) continue;
      if (!hasValidCoordinates(f.lat, f.lng)) continue;

      // Skip if it has been acted upon (resolved/completed)
      final isActiveOrUnassigned =
          f.verificationStatus == null ||
          const {'Assigned', 'Reassigned'}.contains(f.verificationStatus);
      if (!isActiveOrUnassigned) continue;

      // Skip if it was resolved to Green by admin without inspection
      if (f.flagColor == 'Green') continue;

      markers.add(
        Marker(
          markerId: MarkerId('my_flag_${f.logID}'),
          position: LatLng(f.lat, f.lng),
          clusterManagerId: _flagClusterManagerId,
          infoWindow: InfoWindow(
            title: f.detectedName,
            snippet: 'You flagged this • ${f.flagColor}',
          ),
          icon: BitmapDescriptor.defaultMarkerWithHue(
            BitmapDescriptor.hueYellow,
          ),
          onTap: () => f.flagColor == 'Yellow'
              ? _onYellowFlagMarkerTap(f)
              : _onYellowFlagTap(f),
        ),
      );
    }

    return markers;
  }

  Future<void> _onYellowTaskMarkerTap(InspectionTask task) async {
    final candidates = buildYellowFlagCandidates(
      tasks: _tasks,
      flags: _myFlags,
    );
    final tapped = YellowFlagCandidate.forTask(task);
    await _openNearbyYellowCandidates(candidates, tapped);
  }

  Future<void> _onYellowFlagMarkerTap(MyFlag flag) async {
    final candidates = buildYellowFlagCandidates(
      tasks: _tasks,
      flags: _myFlags,
    );
    final tapped = YellowFlagCandidate.forFlag(flag);
    await _openNearbyYellowCandidates(candidates, tapped);
  }

  Future<void> _openNearbyYellowCandidates(
    List<YellowFlagCandidate> candidates,
    YellowFlagCandidate tapped,
  ) async {
    if (!mounted ||
        _isDrawerOpen ||
        _isYellowPickerOpen ||
        _isYellowSelectionResolving) {
      return;
    }
    _isYellowSelectionResolving = true;
    try {
      if (!candidates.any(
        (candidate) => candidate.stableIdentity == tapped.stableIdentity,
      )) {
        _openYellowCandidate(tapped);
        return;
      }

      final controller = _mapController;
      if (controller == null || !widget.isVisible || !_isAppForeground) {
        _openYellowCandidate(tapped);
        return;
      }

      final devicePixelRatio = MediaQuery.devicePixelRatioOf(context);
      // getScreenCoordinate uses native screen pixels; convert this marker-sized
      // Flutter logical-pixel radius before comparing projected coordinates.
      const logicalPixelRadius = 40.0;
      final nearby = await projectAndSelectNearbyYellowCandidates(
        candidates: candidates,
        tappedIdentity: tapped.stableIdentity,
        project: (position) async {
          final point = await controller.getScreenCoordinate(position);
          return YellowFlagScreenPoint(point.x.toDouble(), point.y.toDouble());
        },
        radiusScreenPixels: logicalPixelRadius * devicePixelRatio,
      );
      if (!mounted ||
          _mapController != controller ||
          !widget.isVisible ||
          !_isAppForeground) {
        return;
      }
      if (nearby == null ||
          nearby.isEmpty ||
          !nearby.any(
            (candidate) => candidate.stableIdentity == tapped.stableIdentity,
          )) {
        _openYellowCandidate(tapped);
        return;
      }
      if (nearby.length == 1) {
        _openYellowCandidate(nearby.single);
        return;
      }

      _isYellowPickerOpen = true;
      setState(() => _isDrawerOpen = true);
      widget.onDrawerToggled?.call(true);
      YellowFlagCandidate? selected;
      try {
        selected = await showModalBottomSheet<YellowFlagCandidate>(
          context: context,
          isScrollControlled: true,
          backgroundColor: context.adaptiveSurface,
          shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          builder: (sheetContext) => YellowFlagLocationPicker(
            candidates: nearby,
            onSelected: (candidate) =>
                Navigator.of(sheetContext).pop(candidate),
          ),
        );
      } finally {
        _isYellowPickerOpen = false;
        widget.onDrawerToggled?.call(false);
        if (mounted) setState(() => _isDrawerOpen = false);
      }

      if (selected != null && mounted && widget.isVisible && _isAppForeground) {
        _openYellowCandidate(selected);
      }
    } finally {
      _isYellowSelectionResolving = false;
    }
  }

  void _openYellowCandidate(YellowFlagCandidate candidate) {
    openYellowFlagCandidate(
      candidate: candidate,
      onTask: _onTaskTap,
      onFlag: _onYellowFlagTap,
    );
  }

  void _toggleDocker() {
    final newState = !_isDockerExpanded;
    setState(() {
      _isDockerExpanded = newState;
      if (!_isDockerExpanded) _isFirstLoad = false;
    });
    widget.onDrawerToggled?.call(newState);
  }

  Future<void> _goToCurrentLocation() async {
    final result = await _locationService.getCurrentLocation();
    final hasLocationAccess =
        result.issue != InspectionLocationIssue.locationServicesDisabled &&
        result.issue != InspectionLocationIssue.permissionDenied &&
        result.issue != InspectionLocationIssue.permissionDeniedForever;
    if (mounted && _hasLocationPermission != hasLocationAccess) {
      setState(() => _hasLocationPermission = hasLocationAccess);
    }

    if (result.hasFix) {
      final position = LatLng(result.fix!.latitude, result.fix!.longitude);
      if (mounted) setState(() => _pedestrianPosition = position);
      _startPedestrianTracking();
      await _mapController?.animateCamera(
        CameraUpdate.newCameraPosition(
          CameraPosition(target: position, zoom: 16),
        ),
      );
      return;
    }

    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(result.message)));
    }
  }

  Future<void> _refreshLocationAvailability() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      final permission = await Geolocator.checkPermission();
      final hasLocationAccess =
          serviceEnabled &&
          (permission == LocationPermission.whileInUse ||
              permission == LocationPermission.always);
      if (mounted && _hasLocationPermission != hasLocationAccess) {
        setState(() => _hasLocationPermission = hasLocationAccess);
      }
      if (hasLocationAccess && widget.isVisible && _isAppForeground) {
        _startPedestrianTracking();
      } else {
        _stopPedestrianTracking();
        if (mounted && _pedestrianPosition != null) {
          setState(() => _pedestrianPosition = null);
        }
      }
    } catch (error) {
      debugPrint('Could not refresh map location availability: $error');
      if (mounted && _hasLocationPermission) {
        setState(() => _hasLocationPermission = false);
      }
      _stopPedestrianTracking();
    }
  }

  void _startPedestrianTracking() {
    if (!_hasLocationPermission ||
        !widget.isVisible ||
        !_isAppForeground ||
        _pedestrianPositionSubscription != null) {
      return;
    }

    _pedestrianPositionSubscription =
        Geolocator.getPositionStream(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 5,
          ),
        ).listen(
          (position) {
            if (!position.latitude.isFinite ||
                !position.longitude.isFinite ||
                !position.accuracy.isFinite ||
                position.accuracy < 0 ||
                position.accuracy > 100 ||
                position.latitude < -90 ||
                position.latitude > 90 ||
                position.longitude < -180 ||
                position.longitude > 180 ||
                !mounted) {
              return;
            }
            setState(() {
              _pedestrianPosition = LatLng(
                position.latitude,
                position.longitude,
              );
            });
          },
          onError: (Object error) {
            debugPrint('Pedestrian location tracking failed: $error');
            _stopPedestrianTracking();
          },
        );
  }

  void _stopPedestrianTracking() {
    final subscription = _pedestrianPositionSubscription;
    _pedestrianPositionSubscription = null;
    if (subscription != null) unawaited(subscription.cancel());
  }

  void _selectRouteDestination(InspectionTask task) {
    if (_routeTask?.assignmentKey == task.assignmentKey) return;
    _routeUiGeneration++;
    _walkingRouteCoordinator.selectDestination(task.assignmentKey);
    setState(() {
      _routeTask = task;
      _walkingRoute = null;
      _routeMessage = null;
      _isRouteLoading = false;
    });
  }

  Future<void> _requestWalkingRoute(InspectionTask task) async {
    if (_isRouteLoading) return;
    _selectRouteDestination(task);
    final taskIdentity = task.assignmentKey;
    final requestGeneration = ++_routeUiGeneration;

    setState(() {
      _routeTask = task;
      _walkingRoute = null;
      _routeMessage = null;
      _isRouteLoading = true;
    });

    void finishWithMessage(String message) {
      if (!mounted || requestGeneration != _routeUiGeneration) return;
      setState(() {
        _isRouteLoading = false;
        _routeMessage = message;
      });
    }

    if (ConnectivityService().isOffline.value) {
      finishWithMessage(
        'Walking directions require an internet connection. GPS can still work offline.',
      );
      return;
    }

    final latitude = task.latitude;
    final longitude = task.longitude;
    if (latitude == null ||
        longitude == null ||
        !latitude.isFinite ||
        !longitude.isFinite ||
        latitude < -90 ||
        latitude > 90 ||
        longitude < -180 ||
        longitude > 180) {
      finishWithMessage('This task has no valid destination coordinates.');
      return;
    }

    final location = await _locationService.getCurrentLocation();
    if (!mounted || requestGeneration != _routeUiGeneration) return;
    if (!location.hasFix) {
      finishWithMessage(location.message);
      return;
    }

    final result = await _walkingRouteCoordinator.request(
      WalkingRouteRequest(
        taskIdentity: taskIdentity,
        origin: LatLng(location.fix!.latitude, location.fix!.longitude),
        destination: LatLng(latitude, longitude),
      ),
    );
    if (!mounted || requestGeneration != _routeUiGeneration) return;

    final route = result.route;
    setState(() {
      _isRouteLoading = false;
      _walkingRoute = route;
      _routeMessage = route == null
          ? switch (result.failure) {
              WalkingRouteFailure.providerNotConfigured =>
                'Walking directions are not enabled for this app. No route request was sent.',
              WalkingRouteFailure.offline =>
                'Walking directions require an internet connection.',
              WalkingRouteFailure.noRoute =>
                'No valid walking route was returned.',
              WalkingRouteFailure.requestInProgress =>
                'A directions request is already in progress.',
              WalkingRouteFailure.stale => null,
              WalkingRouteFailure.unavailable ||
              null => 'Walking directions are temporarily unavailable.',
            }
          : null;
    });
  }

  void _clearWalkingRoute() {
    _routeUiGeneration++;
    _walkingRouteCoordinator.selectDestination('');
    setState(() {
      _routeTask = null;
      _walkingRoute = null;
      _routeMessage = null;
      _isRouteLoading = false;
    });
  }

  String _formatRouteDistance(int meters) =>
      meters >= 1000 ? '${(meters / 1000).toStringAsFixed(1)} km' : '$meters m';

  String _formatRouteDuration(double seconds) {
    final totalMinutes = (seconds / 60).round();
    if (totalMinutes < 60) return '$totalMinutes min';
    final hours = totalMinutes ~/ 60;
    final minutes = totalMinutes % 60;
    return minutes == 0 ? '$hours hr' : '$hours hr $minutes min';
  }

  // ── Open inspection modal ─────────────────────────────────────────────────
  void _onTaskTap(InspectionTask task) async {
    if (_isDrawerOpen) return;
    _selectRouteDestination(task);
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => InspectionModal(
        task: task,
        onSubmitted: () => _fetchTasks(),
        onWalkingDirections: () => _requestWalkingRoute(task),
        onViewStreetView: _openStreetView,
      ),
    );
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  void _onYellowFlagTap(MyFlag flag) async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            top: 0,
            right: 16,
            child: Image.asset('assets/images/standing.png', height: 240),
          ),
          Container(
            margin: const EdgeInsets.only(top: 110),
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: context.adaptiveSurface,
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(24),
              ),
            ),
            child: SafeArea(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Reported Flag',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: context.adaptiveTextDark,
                    ),
                  ),
                  const SizedBox(height: 16),
                  _buildDetailRow('Business Name', flag.detectedName),
                  _buildDetailRow('Color', flag.flagColor),
                  _buildDetailRow(
                    'Status',
                    flag.verificationStatus ?? 'Pending',
                  ),
                  if (flag.notes != null && flag.notes!.isNotEmpty)
                    _buildDetailRow('Notes', flag.notes!),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () {
                        Navigator.of(context).pop();
                        unawaited(_openStreetView(LatLng(flag.lat, flag.lng)));
                      },
                      icon: const Icon(Icons.streetview_rounded),
                      label: const Text('View Street View'),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.gold.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: AppColors.gold.withValues(alpha: 0.3),
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.info_outline_rounded,
                          color: AppColors.gold,
                          size: 20,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'This yellow flag needs to be reviewed by the admin before you can proceed with any official inspection.',
                            style: TextStyle(
                              fontSize: 13,
                              color: context.adaptiveTextDark,
                              height: 1.4,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => Navigator.pop(context),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.gold,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      child: const Text(
                        'Close',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: const TextStyle(
                fontWeight: FontWeight.w600,
                color: Colors.grey,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: context.adaptiveTextDark,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWalkingRouteCard(BuildContext context) {
    final route = _walkingRoute;
    final details = <String>[
      if (route?.distanceMeters case final meters?)
        'Distance: ${_formatRouteDistance(meters)}',
      if (route?.durationSeconds case final seconds?)
        'Walking time: ${_formatRouteDuration(seconds)}',
    ];
    return Card(
      elevation: 4,
      color: context.adaptiveSurface,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.directions_walk_rounded,
                  color: Color(0xFF1565C0),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _isRouteLoading
                        ? 'Getting walking directions…'
                        : 'Walking route to ${_routeTask!.detectedName}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: context.adaptiveTextDark,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (_routeMessage != null) ...[
              const SizedBox(height: 6),
              Text(
                _routeMessage!,
                style: TextStyle(color: context.adaptiveTextDark, fontSize: 12),
              ),
            ],
            if (details.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                details.join(' · '),
                style: TextStyle(color: context.adaptiveTextDark, fontSize: 12),
              ),
            ],
            if (!_isRouteLoading)
              Wrap(
                spacing: 4,
                children: [
                  TextButton(
                    onPressed: () => _requestWalkingRoute(_routeTask!),
                    child: const Text('Refresh Route'),
                  ),
                  TextButton(
                    onPressed: _clearWalkingRoute,
                    child: const Text('Clear Route'),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  // ── Open yellow flag sheet ────────────────────────────────────────────────
  void _showYellowFlagSheet() async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _YellowFlagSheet(
        onSuccess: (MyFlag newFlag) {
          if (!mounted) return;
          // Optimistically add the new flag to the map before the next poll.
          setState(() {
            _submittedFlags.addAfterSuccessfulSubmission(newFlag);
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              backgroundColor: AppColors.gold,
              behavior: SnackBarBehavior.floating,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              content: const Row(
                children: [
                  Icon(Icons.flag_rounded, color: Colors.black87, size: 20),
                  SizedBox(width: 10),
                  Text(
                    'Yellow flag reported successfully.',
                    style: TextStyle(
                      color: Colors.black87,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          );
        },
        onPendingSync: () {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Saved locally · Pending Sync'),
              behavior: SnackBarBehavior.floating,
            ),
          );
        },
      ),
    );
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  Widget _buildMapLegend(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.adaptiveSurface.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: context.isDarkMode ? Colors.white24 : Colors.black12,
        ),
        boxShadow: const [
          BoxShadow(color: Colors.black12, blurRadius: 8, offset: Offset(0, 4)),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Map Legend',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                  color: context.adaptiveTextDark,
                ),
              ),
              const SizedBox(width: 24),
              GestureDetector(
                onTap: () => setState(() => _isLegendOpen = false),
                child: Icon(
                  Icons.close,
                  size: 16,
                  color: context.adaptiveTextMid,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _buildLegendItem(Colors.red, 'Unregistered'),
          _buildLegendItem(Colors.orange, 'Warning / Notice'),
          _buildLegendItem(Colors.yellow, 'Inspector Flagged'),
          _buildLegendItem(Colors.green, 'Verified / Clear'),
          _buildLegendItem(Colors.black, 'Blacklisted / Non-Responsive'),
          _buildLegendItem(const Color(0xFF7C3AED), 'Closed / Abandoned'),
        ],
      ),
    );
  }

  Widget _buildLegendItem(Color color, String label) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.location_on, color: color, size: 16),
          const SizedBox(width: 8),
          Text(
            label,
            style: TextStyle(fontSize: 12, color: context.adaptiveTextDark),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final screenHeight = MediaQuery.of(context).size.height;
    final screenWidth = MediaQuery.of(context).size.width;
    final paddingTop = MediaQuery.of(context).padding.top;
    final compactHeader = screenWidth < 380;
    final hasCount =
        !_loadingTasks &&
        (_dockerTab == 'tasks' ? _tasks.isNotEmpty : _myFlags.isNotEmpty);
    final hasSort = !_loadingTasks && _tasks.isNotEmpty;

    final dockerTitle = _isFirstLoad
        ? Text(
            "Saan ang Sinsay?",
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.bold,
              color: context.adaptiveTextDark,
            ),
          )
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              GestureDetector(
                onTap: () => setState(() => _dockerTab = 'tasks'),
                child: Text(
                  "Tasks",
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: _dockerTab == 'tasks'
                        ? context.adaptiveTextDark
                        : Colors.grey,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              GestureDetector(
                onTap: () => setState(() => _dockerTab = 'flags'),
                child: Text(
                  "My Flags",
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: _dockerTab == 'flags'
                        ? context.adaptiveTextDark
                        : Colors.grey,
                  ),
                ),
              ),
            ],
          );
    final countBadge = hasCount
        ? Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: context.isDarkMode
                  ? Colors.black
                  : AppColors.darkGreen.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              _dockerTab == 'tasks'
                  ? '${_tasks.length} task${_tasks.length != 1 ? 's' : ''}'
                  : '${_myFlags.length} flag${_myFlags.length != 1 ? 's' : ''}',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: context.isDarkMode ? Colors.white : AppColors.darkGreen,
              ),
            ),
          )
        : const SizedBox.shrink();
    final sortControl = hasSort
        ? GestureDetector(
            onTap: () => setState(
              () => _sortBy = _sortBy == 'newest' ? 'oldest' : 'newest',
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: context.isDarkMode
                    ? Colors.black
                    : const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: context.isDarkMode ? Colors.white : Colors.transparent,
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _sortBy == 'newest'
                        ? Icons.arrow_downward_rounded
                        : Icons.arrow_upward_rounded,
                    size: 12,
                    color: context.isDarkMode
                        ? Colors.white
                        : const Color(0xFF64748B),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    _sortBy == 'newest' ? 'Newest' : 'Oldest',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: context.isDarkMode
                          ? Colors.white
                          : const Color(0xFF64748B),
                    ),
                  ),
                ],
              ),
            ),
          )
        : const SizedBox.shrink();

    // Reactively update map style if theme changes while map is already created

    return Scaffold(
      backgroundColor: Colors.transparent,
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: Padding(
          padding: const EdgeInsets.only(left: 12),
          child: Align(
            alignment: Alignment.center,
            child: Showcase(
              key: MainLayout.mapLegendsTourKey,
              title: 'Legends',
              description:
                  'Tap this to see what the different colored map markers represent.',
              targetPadding: const EdgeInsets.all(4),
              child: FloatingActionButton(
                mini: true,
                backgroundColor: context.isDarkMode
                    ? Colors.black
                    : Colors.white,
                heroTag: 'legend_toggle',
                onPressed: () => setState(() => _isLegendOpen = !_isLegendOpen),
                child: Icon(
                  Icons.legend_toggle_rounded,
                  color: context.isDarkMode
                      ? Colors.white
                      : AppColors.darkGreen,
                ),
              ),
            ),
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FloatingActionButton(
              mini: true,
              backgroundColor: context.isDarkMode ? Colors.black : Colors.white,
              heroTag: 'refresh',
              onPressed: _loadingTasks ? null : () => _fetchTasks(),
              child: _loadingTasks
                  ? SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: context.isDarkMode
                            ? Colors.white
                            : AppColors.darkGreen,
                      ),
                    )
                  : Icon(
                      Icons.refresh,
                      color: context.isDarkMode
                          ? Colors.white
                          : AppColors.darkGreen,
                    ),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          // ── 1. Google Map ────────────────────────────────────────────────
          Positioned.fill(
            child: GoogleMap(
              style: context.isDarkMode ? AppMapStyles.darkMapStyle : "[]",
              padding: EdgeInsets.only(
                bottom: _isDockerExpanded ? screenHeight * 0.5 : 0.0,
              ),
              initialCameraPosition: _initialCamera,
              mapType: _currentMapType,
              clusterManagers: {
                ClusterManager(clusterManagerId: _flagClusterManagerId),
              },
              markers: _buildFlagMarkers(),
              polylines: _walkingRoute == null
                  ? const <Polyline>{}
                  : {_walkingRoute!.toPolyline()},
              onCameraMove: (position) {
                _currentCameraPosition = position;
              },
              onTap: (position) {
                if (_streetViewPickMode) {
                  unawaited(_openStreetView(position));
                }
              },
              onMapCreated: (controller) async {
                _mapController = controller;
                await _goToCurrentLocation();
                _syncMapToTasks();
              },
              myLocationEnabled:
                  _hasLocationPermission &&
                  widget.isVisible &&
                  _isAppForeground,
              myLocationButtonEnabled: false,
              zoomControlsEnabled: false,
              mapToolbarEnabled: false,
            ),
          ),

          if (_routeTask != null &&
              (_walkingRoute != null ||
                  _routeMessage != null ||
                  _isRouteLoading))
            Positioned(
              top: paddingTop + kToolbarHeight + 8,
              left: 16,
              right: 72,
              child: _buildWalkingRouteCard(context),
            ),

          if (_streetViewPickMode)
            Positioned(
              top: paddingTop + kToolbarHeight + 8,
              left: 16,
              right: 72,
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 8, 6, 8),
                  child: Row(
                    children: [
                      const Icon(Icons.streetview_rounded, size: 20),
                      const SizedBox(width: 8),
                      const Expanded(
                        child: Text('Tap the map to view nearby Street View.'),
                      ),
                      TextButton(
                        onPressed: () =>
                            setState(() => _streetViewPickMode = false),
                        child: const Text('Cancel'),
                      ),
                    ],
                  ),
                ),
              ),
            ),

          // ── 1.5. Legend ───────────────────────────────────────────────────
          if (_isLegendOpen)
            Positioned(
              top: paddingTop + kToolbarHeight + 8,
              left: 16,
              child: _buildMapLegend(context),
            ),

          // ── 2. Map View Controls (+/−/recenter) ─────────────────────────
          Positioned(
            top: paddingTop + kToolbarHeight + 16,
            right: 16,
            child: Showcase(
              key: MainLayout.mapControlsTourKey,
              title: 'Map Controls',
              description:
                  'Use these to zoom, center on your location, or toggle 3D view.',
              targetPadding: const EdgeInsets.all(4),
              child: Column(
                children: [
                  _MapControlButton(
                    icon: Icons.add,
                    tooltip: 'Zoom In',
                    active: false,
                    onTap: () {
                      _mapController?.animateCamera(CameraUpdate.zoomIn());
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.remove,
                    tooltip: 'Zoom Out',
                    active: false,
                    onTap: () {
                      _mapController?.animateCamera(CameraUpdate.zoomOut());
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.my_location,
                    tooltip: 'Recenter on My Location',
                    active: false,
                    onTap: () {
                      _goToCurrentLocation();
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.refresh_rounded,
                    tooltip: 'Map blank? Refresh view',
                    active: false,
                    onTap: _goToCurrentLocation,
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: _currentMapType == MapType.normal
                        ? Icons.satellite_alt_rounded
                        : Icons.map_rounded,
                    tooltip: 'Toggle Map Type',
                    active: _currentMapType != MapType.normal,
                    onTap: () {
                      setState(() {
                        _currentMapType = _currentMapType == MapType.normal
                            ? MapType.hybrid
                            : MapType.normal;
                      });
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.view_in_ar_rounded,
                    tooltip: 'Toggle 3D View',
                    active: _is3DView,
                    onTap: () {
                      if (_mapController == null) return;
                      setState(() {
                        _is3DView = !_is3DView;
                      });
                      final position = _currentCameraPosition ?? _initialCamera;
                      _mapController!.animateCamera(
                        CameraUpdate.newCameraPosition(
                          CameraPosition(
                            target: position.target,
                            zoom: position.zoom,
                            bearing: position.bearing,
                            tilt: _is3DView ? 60.0 : 0.0,
                          ),
                        ),
                      );
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.zoom_out_rounded,
                    tooltip: 'Zoom out',
                    active: false,
                    onTap: () {
                      _mapController?.animateCamera(CameraUpdate.zoomOut());
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.zoom_in_rounded,
                    tooltip: 'Zoom in',
                    active: false,
                    onTap: () {
                      _mapController?.animateCamera(CameraUpdate.zoomIn());
                    },
                  ),
                  const SizedBox(height: 6),
                  _MapControlButton(
                    icon: Icons.streetview_rounded,
                    tooltip: 'Street View · choose a map location',
                    active: _streetViewPickMode,
                    onTap: _beginStreetViewLocationPick,
                  ),
                ],
              ),
            ),
          ),

          // ── 3. Animated Bottom Docker (short-file behavior) ──────────────
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: AnimatedSlide(
              duration: const Duration(milliseconds: 500),
              curve: Curves.easeInOutQuart,
              offset: _isDockerExpanded ? Offset.zero : const Offset(0, 1.2),
              child: Container(
                decoration: const BoxDecoration(
                  borderRadius: BorderRadius.vertical(top: Radius.circular(32)),
                  boxShadow: [BoxShadow(blurRadius: 20, color: Colors.black26)],
                ),
                child: ClipRRect(
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(32),
                  ),
                  child: BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
                    child: Container(
                      height: screenHeight * 0.5,
                      decoration: BoxDecoration(
                        color: context.adaptiveSurface.withValues(alpha: 0.85),
                      ),
                      child: GestureDetector(
                        onVerticalDragUpdate: (details) {
                          if (details.primaryDelta! > 10) {
                            if (_isDockerExpanded) _toggleDocker();
                          }
                        },
                        onVerticalDragEnd: (details) {
                          if ((details.primaryVelocity ?? 0) > 200) {
                            if (_isDockerExpanded) _toggleDocker();
                          }
                        },
                        behavior: HitTestBehavior.opaque,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            // Handle — tap to dismiss
                            GestureDetector(
                              onTap: _toggleDocker,
                              behavior: HitTestBehavior.opaque,
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  vertical: 14,
                                ),
                                child: Center(
                                  child: Container(
                                    width: 40,
                                    height: 5,
                                    decoration: BoxDecoration(
                                      color: Colors.grey[300],
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                            Flexible(
                              child: Padding(
                                padding: const EdgeInsets.all(24.0),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    if (compactHeader) ...[
                                      Row(
                                        children: [
                                          Expanded(child: dockerTitle),
                                          IconButton(
                                            icon: Icon(
                                              Icons.close_rounded,
                                              color: context.adaptiveTextDark,
                                            ),
                                            onPressed: _toggleDocker,
                                          ),
                                        ],
                                      ),
                                      if (hasCount || hasSort)
                                        Padding(
                                          padding: const EdgeInsets.only(
                                            top: 6,
                                          ),
                                          child: Row(
                                            children: [
                                              countBadge,
                                              const Spacer(),
                                              sortControl,
                                            ],
                                          ),
                                        ),
                                    ] else
                                      Row(
                                        children: [
                                          Expanded(child: dockerTitle),
                                          if (hasCount) ...[
                                            const SizedBox(width: 8),
                                            countBadge,
                                          ],
                                          if (hasSort) ...[
                                            const SizedBox(width: 8),
                                            sortControl,
                                          ],
                                          IconButton(
                                            icon: Icon(
                                              Icons.close_rounded,
                                              color: context.adaptiveTextDark,
                                            ),
                                            onPressed: _toggleDocker,
                                          ),
                                        ],
                                      ),
                                    const SizedBox(height: 16),

                                    // Task list
                                    Flexible(
                                      child: _dockerTab == 'flags'
                                          ? _myFlags.isEmpty
                                                ? Padding(
                                                    padding:
                                                        const EdgeInsets.symmetric(
                                                          vertical: 32,
                                                        ),
                                                    child: Center(
                                                      child: Column(
                                                        mainAxisSize:
                                                            MainAxisSize.min,
                                                        children: [
                                                          Icon(
                                                            Icons.flag_outlined,
                                                            color: Colors
                                                                .grey[400],
                                                            size: 48,
                                                          ),
                                                          const SizedBox(
                                                            height: 12,
                                                          ),
                                                          Text(
                                                            'No yellow flags submitted yet.',
                                                            style: TextStyle(
                                                              color: Colors
                                                                  .grey[500],
                                                              fontSize: 14,
                                                            ),
                                                          ),
                                                        ],
                                                      ),
                                                    ),
                                                  )
                                                : RefreshIndicator(
                                                    color: AppColors.gold,
                                                    onRefresh: () =>
                                                        _fetchMyFlags(),
                                                    child: ListView.builder(
                                                      shrinkWrap: true,
                                                      padding: EdgeInsets.zero,
                                                      physics:
                                                          const AlwaysScrollableScrollPhysics(),
                                                      itemCount:
                                                          _myFlags.length,
                                                      itemBuilder: (context, index) {
                                                        final f =
                                                            _myFlags[_myFlags
                                                                    .length -
                                                                1 -
                                                                index]; // reverse chronological
                                                        return GestureDetector(
                                                          onTap: () =>
                                                              _onYellowFlagTap(
                                                                f,
                                                              ),
                                                          child: Container(
                                                            margin:
                                                                const EdgeInsets.only(
                                                                  bottom: 12,
                                                                ),
                                                            padding:
                                                                const EdgeInsets.all(
                                                                  16,
                                                                ),
                                                            decoration: BoxDecoration(
                                                              color:
                                                                  context
                                                                      .isDarkMode
                                                                  ? Colors
                                                                        .grey[900]
                                                                  : Colors
                                                                        .white,
                                                              borderRadius:
                                                                  BorderRadius.circular(
                                                                    16,
                                                                  ),
                                                              border: Border.all(
                                                                color:
                                                                    context
                                                                        .isDarkMode
                                                                    ? Colors
                                                                          .grey[800]!
                                                                    : Colors
                                                                          .grey[200]!,
                                                              ),
                                                            ),
                                                            child: Row(
                                                              children: [
                                                                Container(
                                                                  padding:
                                                                      const EdgeInsets.all(
                                                                        10,
                                                                      ),
                                                                  decoration: BoxDecoration(
                                                                    color: AppColors
                                                                        .gold
                                                                        .withValues(
                                                                          alpha:
                                                                              0.1,
                                                                        ),
                                                                    shape: BoxShape
                                                                        .circle,
                                                                  ),
                                                                  child: const Icon(
                                                                    Icons
                                                                        .flag_rounded,
                                                                    color:
                                                                        AppColors
                                                                            .gold,
                                                                    size: 20,
                                                                  ),
                                                                ),
                                                                const SizedBox(
                                                                  width: 16,
                                                                ),
                                                                Expanded(
                                                                  child: Column(
                                                                    crossAxisAlignment:
                                                                        CrossAxisAlignment
                                                                            .start,
                                                                    children: [
                                                                      Text(
                                                                        f.detectedName,
                                                                        style: TextStyle(
                                                                          fontWeight:
                                                                              FontWeight.bold,
                                                                          fontSize:
                                                                              15,
                                                                          color:
                                                                              context.adaptiveTextDark,
                                                                        ),
                                                                      ),
                                                                      const SizedBox(
                                                                        height:
                                                                            4,
                                                                      ),
                                                                      Text(
                                                                        f.verificationStatus ??
                                                                            'Pending',
                                                                        style: TextStyle(
                                                                          color:
                                                                              Colors.grey[500],
                                                                          fontSize:
                                                                              12,
                                                                        ),
                                                                      ),
                                                                    ],
                                                                  ),
                                                                ),
                                                                const Icon(
                                                                  Icons
                                                                      .chevron_right_rounded,
                                                                  color: Colors
                                                                      .grey,
                                                                ),
                                                              ],
                                                            ),
                                                          ),
                                                        );
                                                      },
                                                    ),
                                                  )
                                          : _loadingTasks
                                          ? ListView.builder(
                                              shrinkWrap: true,
                                              physics:
                                                  const NeverScrollableScrollPhysics(),
                                              itemCount: 3,
                                              padding: EdgeInsets.zero,
                                              itemBuilder: (context, index) =>
                                                  Padding(
                                                    padding:
                                                        const EdgeInsets.only(
                                                          bottom: 12.0,
                                                        ),
                                                    child: Shimmer.fromColors(
                                                      baseColor:
                                                          context.isDarkMode
                                                          ? Colors.grey[800]!
                                                          : Colors.grey[300]!,
                                                      highlightColor:
                                                          context.isDarkMode
                                                          ? Colors.grey[700]!
                                                          : Colors.grey[100]!,
                                                      child: Container(
                                                        height: 120,
                                                        decoration: BoxDecoration(
                                                          color: Colors.white,
                                                          borderRadius:
                                                              BorderRadius.circular(
                                                                16,
                                                              ),
                                                        ),
                                                      ),
                                                    ),
                                                  ),
                                            )
                                          : _taskError != null
                                          ? Padding(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    vertical: 32,
                                                  ),
                                              child: Center(
                                                child: Column(
                                                  mainAxisSize:
                                                      MainAxisSize.min,
                                                  children: [
                                                    const Icon(
                                                      Icons.wifi_off,
                                                      color: Colors.grey,
                                                      size: 40,
                                                    ),
                                                    const SizedBox(height: 12),
                                                    Text(
                                                      _taskError!,
                                                      style: const TextStyle(
                                                        color: Colors.grey,
                                                      ),
                                                    ),
                                                    const SizedBox(height: 12),
                                                    TextButton(
                                                      onPressed: _fetchTasks,
                                                      child: const Text(
                                                        'Retry',
                                                      ),
                                                    ),
                                                  ],
                                                ),
                                              ),
                                            )
                                          : _tasks.isEmpty
                                          ? Padding(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    vertical: 32,
                                                  ),
                                              child: Center(
                                                child: Column(
                                                  mainAxisSize:
                                                      MainAxisSize.min,
                                                  children: [
                                                    Icon(
                                                      Icons
                                                          .check_circle_outline,
                                                      color: Colors.grey[400],
                                                      size: 48,
                                                    ),
                                                    const SizedBox(height: 12),
                                                    Text(
                                                      'No assignments yet.',
                                                      style: TextStyle(
                                                        color: Colors.grey[500],
                                                        fontSize: 14,
                                                      ),
                                                    ),
                                                  ],
                                                ),
                                              ),
                                            )
                                          : RefreshIndicator(
                                              color: AppColors.darkGreen,
                                              onRefresh: () => _fetchTasks(),
                                              child: ListView.builder(
                                                shrinkWrap: true,
                                                padding: EdgeInsets.zero,
                                                physics:
                                                    const AlwaysScrollableScrollPhysics(),
                                                itemCount: _sortedTasks.length,
                                                itemBuilder: (context, index) =>
                                                    InspectionCard(
                                                      task: _sortedTasks[index],
                                                      onTap: () => _onTaskTap(
                                                        _sortedTasks[index],
                                                      ),
                                                    ),
                                              ),
                                            ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),

          // ── 4. Floating Action Buttons (Tasks & Flag) ───────────────────────────
          Positioned(
            bottom: _isDockerExpanded ? screenHeight * 0.5 + 16 : 140,
            right: 16,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(28),
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                child: Container(
                  decoration: BoxDecoration(
                    color: context.adaptiveSurface.withValues(alpha: 0.8),
                    borderRadius: BorderRadius.circular(28),
                    border: Border.all(
                      color: context.isDarkMode
                          ? Colors.white24
                          : Colors.black12,
                    ),
                  ),
                  child: Column(
                    children: [
                      Showcase(
                        key: MainLayout.mapAssignmentsBtnTourKey,
                        title: 'Tasks Menu',
                        description:
                            'Swipe up or tap here to view and manage your inspection assignments.',
                        targetPadding: const EdgeInsets.all(4),
                        child: IconButton(
                          icon: const Icon(Icons.assignment_rounded),
                          color: context.adaptiveTextDark,
                          tooltip: 'Inspection Tasks',
                          onPressed: _toggleDocker,
                        ),
                      ),
                      Container(
                        width: 32,
                        height: 1,
                        color: context.isDarkMode
                            ? Colors.white24
                            : Colors.black12,
                      ),
                      Showcase(
                        key: MainLayout.mapAddFlagBtnTourKey,
                        title: 'Add Yellow Flag',
                        description:
                            'Notice an unregistered business? Tap here to flag it directly from the map.',
                        targetPadding: const EdgeInsets.all(4),
                        child: IconButton(
                          icon: const Icon(Icons.flag_rounded),
                          color: const Color(0xFFF59E0B),
                          tooltip: 'Flag Business',
                          onPressed: _showYellowFlagSheet,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Map Control Button ───────────────────────────────────────────────────────
class _MapControlButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final bool active;
  final VoidCallback onTap;

  const _MapControlButton({
    required this.icon,
    required this.tooltip,
    required this.active,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: GestureDetector(
        onTap: () {
          HapticFeedback.lightImpact();
          onTap();
        },
        child: Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            boxShadow: [
              BoxShadow(
                blurRadius: 6,
                color: Colors.black.withValues(alpha: 0.12),
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: BackdropFilter(
              filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
              child: Container(
                decoration: BoxDecoration(
                  color: active
                      ? AppColors.darkGreen.withValues(alpha: 0.9)
                      : context.isDarkMode
                      ? Colors.black.withValues(alpha: 0.5)
                      : Colors.white.withValues(alpha: 0.7),
                ),
                child: Icon(
                  icon,
                  size: 18,
                  color: active
                      ? Colors.white
                      : context.isDarkMode
                      ? Colors.white
                      : AppColors.darkGreen,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ─── Result chip (modal) ─────────────────────────────────────────────────────

// ─── Yellow Flag Bottom Sheet ─────────────────────────────────────────────────

class _YellowFlagSheet extends StatefulWidget {
  final void Function(MyFlag) onSuccess;
  final VoidCallback onPendingSync;

  const _YellowFlagSheet({
    required this.onSuccess,
    required this.onPendingSync,
  });

  @override
  State<_YellowFlagSheet> createState() => _YellowFlagSheetState();
}

class _YellowFlagSheetState extends State<_YellowFlagSheet> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _streetAddressCtrl = TextEditingController();
  final _latCtrl = TextEditingController();
  final _lngCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();

  final FlagService _flagService = FlagService();
  final BoundaryService _boundaryService = BoundaryService();
  final InspectionLocationService _locationService =
      InspectionLocationService();
  final YellowFlagAddressSearchService _addressSearchService =
      YellowFlagAddressSearchService();

  List<Barangay> _barangays = [];
  List<YellowFlagDraft> _savedDrafts = [];
  List<YellowFlagAddressCandidate> _addressCandidates = [];
  Barangay? _selectedBarangay;
  ResolvedAdministrativeArea? _resolvedArea;
  bool _loadingBarangays = true;
  bool _fetchingLocation = false;
  bool _submitting = false;
  bool _isOutsideBoundary = false;
  bool _isBarangayMismatch = false;
  bool _searchingAddress = false;
  bool _locationConfirmed = false;
  bool _isAddressLocation = false;
  bool _addressLocationNeedsRefresh = false;
  bool _addressSearchCompleted = false;
  String? _errorMsg;
  String? _locationMessage;
  YellowFlagAddressSearchFailure? _addressSearchFailure;
  int _addressSearchGeneration = 0;
  Timer? _addressSearchDebounceTimer;

  // True when the current GPS coordinates populated the barangay selection.
  bool _isGpsLocked = false;
  bool _usingLocalBarangayList = false;
  String? _editingDraftId;

  // True once the user has interacted with location in any way (pressed
  // "Use Current Location" or changed barangay). Guards against the slow,
  // silent GPS fetch kicked off in initState resolving *after* the user
  // has already made their own choice and stomping it back.
  bool _locationTouched = false;

  bool get _canSubmit =>
      !_submitting &&
      !_fetchingLocation &&
      !_searchingAddress &&
      !_isOutsideBoundary &&
      !_isBarangayMismatch &&
      _locationConfirmed &&
      !_addressLocationNeedsRefresh &&
      _selectedBarangay != null &&
      _latCtrl.text.isNotEmpty &&
      _lngCtrl.text.isNotEmpty;

  @override
  void initState() {
    super.initState();
    _boundaryService.loadBoundaries();
    _loadBarangays();
    _loadSavedDrafts();
  }

  Future<void> _applyCoordinates(
    double lat,
    double lng, {
    bool silent = false,
    bool updateBarangay = true,
    bool confirmed = true,
  }) async {
    await _boundaryService.loadBoundaries();

    final area = _boundaryService.resolveAdministrativeArea(lat, lng);
    if (area == null) {
      if (!mounted) return;
      setState(() {
        _latCtrl.text = lat.toStringAsFixed(6);
        _lngCtrl.text = lng.toStringAsFixed(6);
        if (updateBarangay) _selectedBarangay = null;
        _resolvedArea = null;
        _isGpsLocked = false;
        _locationTouched = true;
        _isOutsideBoundary = true;
        _isBarangayMismatch = false;
        _locationConfirmed = confirmed;
        _errorMsg = _boundaryService.hasLoadedBoundaries
            ? 'Coordinates are outside the official Mataasnakahoy barangay boundaries.'
            : 'Official boundary data is unavailable. Location cannot be verified.';
      });

      if (!silent && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(_errorMsg!),
            backgroundColor: Colors.red,
            behavior: SnackBarBehavior.floating,
            duration: Duration(seconds: 4),
          ),
        );
      }
      return;
    }

    Barangay? matched;
    final areaKey = BoundaryService.canonicalBarangayKey(area.barangay);
    for (final barangay in _barangays) {
      if (BoundaryService.canonicalBarangayKey(barangay.name) == areaKey) {
        matched = barangay;
        break;
      }
    }

    if (!mounted) return;
    setState(() {
      _latCtrl.text = lat.toStringAsFixed(6);
      _lngCtrl.text = lng.toStringAsFixed(6);
      _resolvedArea = area;
      if (updateBarangay) _selectedBarangay = matched;
      _isGpsLocked = updateBarangay && matched != null;
      _locationTouched = true;
      _isOutsideBoundary = false;
      final selectedMismatch =
          !updateBarangay &&
          _selectedBarangay != null &&
          BoundaryService.canonicalBarangayKey(_selectedBarangay!.name) !=
              areaKey;
      _isBarangayMismatch = selectedMismatch;
      _locationConfirmed = confirmed;
      _errorMsg = selectedMismatch
          ? 'Coordinates resolve to ${area.barangay}, not ${_selectedBarangay!.name}.'
          : (updateBarangay && matched == null)
          ? 'Location resolved to ${area.barangay}, but its registry entry is unavailable.'
          : null;
    });

    if (!silent && mounted) {
      final msg = matched != null
          ? 'Location set to ${matched.name} · ${area.municipality}, ${area.province}'
          : 'Detected ${area.barangay}, but its registry entry is unavailable.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(msg),
          backgroundColor: AppColors.darkGreen,
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 3),
        ),
      );
    }
  }

  void _onStreetAddressChanged(String _) {
    _addressSearchDebounceTimer?.cancel();
    if (_isAddressLocation) {
      setState(() {
        _addressLocationNeedsRefresh = true;
        _locationConfirmed = false;
      });
    }
    _addressSearchGeneration++;
    setState(() {
      _addressCandidates = [];
      _addressSearchFailure = null;
      _addressSearchCompleted = false;
      _searchingAddress = false;
      _locationMessage = null;
    });
    _scheduleAddressSuggestions();
  }

  void _scheduleAddressSuggestions() {
    _addressSearchDebounceTimer?.cancel();
    if (_streetAddressCtrl.text.trim().length < 5) {
      return;
    }
    _addressSearchDebounceTimer = Timer(const Duration(milliseconds: 700), () {
      if (mounted) {
        _searchAddress();
      }
    });
  }

  Future<void> _searchAddress() async {
    _addressSearchDebounceTimer?.cancel();
    final streetAddress = _streetAddressCtrl.text.trim();
    if (streetAddress.isEmpty || _searchingAddress) return;
    final generation = ++_addressSearchGeneration;
    setState(() {
      _searchingAddress = true;
      _addressCandidates = [];
      _addressSearchFailure = null;
      _addressSearchCompleted = false;
      _errorMsg = null;
    });
    try {
      final candidates = await _addressSearchService.search(
        streetAddress: streetAddress,
      );
      if (!mounted || generation != _addressSearchGeneration) return;
      setState(() {
        _searchingAddress = false;
        _addressCandidates = candidates;
        _addressSearchCompleted = true;
      });
    } on YellowFlagAddressSearchException catch (error) {
      if (!mounted || generation != _addressSearchGeneration) return;
      setState(() {
        _searchingAddress = false;
        _addressSearchFailure = error.failure;
        _addressSearchCompleted = true;
      });
    } on Exception catch (error) {
      debugPrint('Yellow Flag address search failed unexpectedly: $error');
      if (!mounted || generation != _addressSearchGeneration) return;
      setState(() {
        _searchingAddress = false;
        _addressSearchFailure = YellowFlagAddressSearchFailure.network;
        _addressSearchCompleted = true;
      });
    }
  }

  Future<void> _selectAddressCandidate(
    YellowFlagAddressCandidate candidate,
  ) async {
    _addressSearchDebounceTimer?.cancel();
    _addressSearchGeneration++;
    _isAddressLocation = true;
    _addressLocationNeedsRefresh = false;
    _streetAddressCtrl.text = candidate.formattedAddress;
    setState(() {
      _addressCandidates = [];
      _addressSearchCompleted = false;
      _locationMessage = null;
    });
    await _applyCoordinates(
      candidate.latitude,
      candidate.longitude,
      silent: true,
      updateBarangay: true,
      confirmed: true,
    );
  }

  Future<void> _autoFillGps({bool silent = false}) async {
    if (_fetchingLocation) return;
    _addressSearchGeneration++;
    _addressSearchDebounceTimer?.cancel();
    setState(() {
      _fetchingLocation = true;
      _locationMessage = null;
      _addressCandidates = [];
      _addressSearchFailure = null;
      _addressSearchCompleted = false;
      _searchingAddress = false;
    });
    try {
      final result = await _locationService.getCurrentLocation();
      if (!mounted) return;
      if (!result.hasFix) {
        setState(() {
          _fetchingLocation = false;
          _errorMsg = result.message;
        });
        if (!silent) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(result.message),
              backgroundColor: Colors.red,
              behavior: SnackBarBehavior.floating,
            ),
          );
        }
        return;
      }
      if (silent && _locationTouched) {
        setState(() => _fetchingLocation = false);
        return;
      }

      if (_loadingBarangays) await _loadBarangays();
      _isAddressLocation = false;
      _addressLocationNeedsRefresh = false;
      _addressSearchGeneration++;
      _addressSearchDebounceTimer?.cancel();
      setState(() {
        _streetAddressCtrl.clear();
        _addressCandidates = [];
        _addressSearchFailure = null;
        _addressSearchCompleted = false;
      });
      await _applyCoordinates(
        result.fix!.latitude,
        result.fix!.longitude,
        silent: silent,
        updateBarangay: true,
      );
      if (!mounted) return;
      try {
        final address = await _addressSearchService.reverseGeocode(
          latitude: result.fix!.latitude,
          longitude: result.fix!.longitude,
        );
        if (!mounted) return;
        setState(() {
          _streetAddressCtrl.text = address ?? '';
          _addressCandidates = [];
          _addressSearchFailure = null;
          _addressSearchCompleted = false;
          _locationMessage = address == null
              ? 'GPS coordinates are set, but no street address was found. Enter the address if known.'
              : null;
        });
      } on YellowFlagAddressSearchException catch (error) {
        if (!mounted) return;
        setState(() {
          _streetAddressCtrl.clear();
          _locationMessage = switch (error.failure) {
            YellowFlagAddressSearchFailure.offline =>
              'GPS coordinates are set. Address lookup needs an internet connection; enter the address if known.',
            YellowFlagAddressSearchFailure.network =>
              'GPS coordinates are set, but the address service could not be reached. Enter the address if known.',
            YellowFlagAddressSearchFailure.unavailable =>
              'GPS coordinates are set, but address lookup is unavailable. Enter the address if known.',
          };
        });
      } on Exception catch (error) {
        debugPrint('Yellow Flag reverse geocoding failed: $error');
        if (!mounted) return;
        setState(() {
          _streetAddressCtrl.clear();
          _locationMessage =
              'GPS coordinates are set, but address lookup failed. Enter the address if known.';
        });
      }
      if (mounted) setState(() => _fetchingLocation = false);
    } catch (error) {
      debugPrint('Could not acquire Yellow Flag GPS location: $error');
      if (mounted) {
        setState(() => _fetchingLocation = false);
        if (!silent) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Could not fetch current location. Please check GPS settings.',
              ),
              backgroundColor: Colors.red,
              behavior: SnackBarBehavior.floating,
            ),
          );
        }
      }
    }
  }

  Future<void> _loadBarangays() async {
    var usingLocalList = false;
    List<Barangay> list;
    try {
      list = await _flagService.fetchBarangays();
      if (list.isEmpty) {
        list = await _flagService.fetchLocalBarangays();
        usingLocalList = true;
      }
    } catch (_) {
      list = await _flagService.fetchLocalBarangays();
      usingLocalList = true;
    }
    try {
      if (mounted) {
        await _boundaryService.loadBoundaries();
        Barangay? matched;
        ResolvedAdministrativeArea? resolvedArea;
        if (_latCtrl.text.isNotEmpty && _lngCtrl.text.isNotEmpty) {
          final lat = double.tryParse(_latCtrl.text);
          final lng = double.tryParse(_lngCtrl.text);
          if (lat != null && lng != null) {
            resolvedArea = _boundaryService.resolveAdministrativeArea(lat, lng);
          }
          if (resolvedArea != null) {
            final areaKey = BoundaryService.canonicalBarangayKey(
              resolvedArea.barangay,
            );
            for (final barangay in list) {
              if (BoundaryService.canonicalBarangayKey(barangay.name) ==
                  areaKey) {
                matched = barangay;
                break;
              }
            }
          }
        }
        setState(() {
          _barangays = list;
          _loadingBarangays = false;
          _usingLocalBarangayList = usingLocalList;
          _resolvedArea = resolvedArea;
          if (_selectedBarangay == null && matched != null) {
            _selectedBarangay = matched;
            _isOutsideBoundary = false;
          }
        });
      }
      await _loadSavedDrafts();
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadingBarangays = false;
          _errorMsg = 'Local barangay boundaries could not be loaded.';
        });
      }
    }
  }

  Future<void> _loadSavedDrafts() async {
    try {
      final drafts = await _flagService.getMyYellowFlagDrafts();
      if (mounted) setState(() => _savedDrafts = drafts);
    } catch (error) {
      debugPrint('Yellow Flag draft list could not be loaded: $error');
    }
  }

  void _resumeDraft(YellowFlagDraft draft) {
    final key = BoundaryService.canonicalBarangayKey(draft.barangayName);
    Barangay? selected;
    for (final barangay in _barangays) {
      if (BoundaryService.canonicalBarangayKey(barangay.name) == key) {
        selected = barangay;
        break;
      }
    }
    setState(() {
      _nameCtrl.text = draft.businessName;
      _latCtrl.text = draft.lat.toStringAsFixed(6);
      _lngCtrl.text = draft.lng.toStringAsFixed(6);
      _notesCtrl.text = draft.notes ?? '';
      _selectedBarangay = selected;
      _editingDraftId = draft.clientSubmissionId;
      _isGpsLocked = false;
      _locationTouched = true;
      _locationConfirmed = true;
      _isAddressLocation = false;
      _addressLocationNeedsRefresh = false;
      _locationMessage = null;
      _isBarangayMismatch = false;
      _isOutsideBoundary = false;
      _errorMsg = draft.lastError;
    });
    unawaited(
      _applyCoordinates(
        draft.lat,
        draft.lng,
        silent: true,
        updateBarangay: false,
        confirmed: true,
      ),
    );
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_selectedBarangay == null) {
      setState(() => _errorMsg = 'Please select a barangay.');
      return;
    }

    final lat = double.tryParse(_latCtrl.text.trim());
    final lng = double.tryParse(_lngCtrl.text.trim());
    if (lat == null || lng == null) {
      setState(() => _errorMsg = 'Coordinates must be valid numbers.');
      return;
    }

    await _boundaryService.loadBoundaries();
    final area = _boundaryService.resolveAdministrativeArea(lat, lng);
    if (area == null) {
      setState(
        () => _errorMsg =
            'Coordinates do not fall within the official Mataasnakahoy barangay boundaries.',
      );
      return;
    }
    if (BoundaryService.canonicalBarangayKey(area.barangay) !=
        BoundaryService.canonicalBarangayKey(_selectedBarangay!.name)) {
      setState(
        () => _errorMsg =
            'Coordinates resolve to ${area.barangay}, not ${_selectedBarangay!.name}.',
      );
      return;
    }

    setState(() {
      _submitting = true;
      _errorMsg = null;
    });

    try {
      final result = await _flagService.submitYellowFlag(
        businessName: _nameCtrl.text.trim(),
        lat: lat,
        lng: lng,
        barangayID: _selectedBarangay!.id,
        barangayName: _selectedBarangay!.name,
        notes: _notesCtrl.text.trim().isEmpty ? null : _notesCtrl.text.trim(),
        clientSubmissionId: _editingDraftId,
      );

      await _loadSavedDrafts();
      if (!mounted) return;
      if (result.status == YellowFlagSubmissionStatus.submitted &&
          result.flag != null) {
        Navigator.of(context).pop();
        widget.onSuccess(result.flag!);
      } else if (result.status == YellowFlagSubmissionStatus.pendingSync) {
        Navigator.of(context).pop();
        widget.onPendingSync();
      } else {
        setState(() {
          _submitting = false;
          _errorMsg = result.message ?? 'Needs Attention: review this report.';
          _editingDraftId = result.clientSubmissionId;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _errorMsg = 'We couldn\'t submit your report. Please try again.';
        });
      }
    }
  }

  @override
  void dispose() {
    _addressSearchDebounceTimer?.cancel();
    _nameCtrl.dispose();
    _streetAddressCtrl.dispose();
    _latCtrl.dispose();
    _lngCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;

    return Container(
      decoration: BoxDecoration(
        color: context.adaptiveSurface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
      ),
      padding: EdgeInsets.fromLTRB(20, 0, 20, bottom + 24),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Handle
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Container(
                  width: 40,
                  height: 5,
                  decoration: BoxDecoration(
                    color: Colors.grey[300],
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),

            // Header
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppColors.lightGold,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(
                    Icons.flag_rounded,
                    color: AppColors.gold,
                    size: 22,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Flag Suspected Business',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.bold,
                          color: context.adaptiveTextDark,
                        ),
                      ),
                      Text(
                        'Mark an unregistered establishment on the map.',
                        style: TextStyle(
                          fontSize: 12,
                          color: context.adaptiveTextMid,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),

            if (_savedDrafts.isNotEmpty) ...[
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Saved reports',
                  style: TextStyle(
                    color: context.adaptiveTextDark,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(height: 6),
              ..._savedDrafts.map((draft) {
                final needsAttention =
                    draft.status == YellowFlagDraftStatus.needsAttention;
                return Card(
                  margin: const EdgeInsets.only(bottom: 6),
                  child: ListTile(
                    dense: true,
                    leading: Icon(
                      needsAttention
                          ? Icons.error_outline_rounded
                          : Icons.cloud_upload_outlined,
                      color: needsAttention ? Colors.red : AppColors.gold,
                    ),
                    title: Text(
                      draft.businessName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      needsAttention
                          ? 'Needs Attention · ${draft.lastError ?? 'Review report'}'
                          : 'Pending Sync · ${draft.barangayName}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: TextButton(
                      onPressed: () => _resumeDraft(draft),
                      child: const Text('Review'),
                    ),
                  ),
                );
              }),
              const SizedBox(height: 10),
            ],

            // Error banner
            if (_errorMsg != null) ...[
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF7ED),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFFDE68A)),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      color: AppColors.gold,
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _errorMsg!,
                        style: const TextStyle(
                          fontSize: 13,
                          color: Color(0xFF92400E),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
            ],

            // Form
            Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Business name
                  TextFormField(
                    controller: _nameCtrl,
                    decoration: InputDecoration(
                      labelText: 'Business Name *',
                      hintText: 'e.g. Aling Nena\'s Sari-Sari Store',
                      prefixIcon: const Icon(Icons.storefront_outlined),
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: context.isDarkMode
                              ? Colors.white
                              : Colors.grey,
                        ),
                      ),
                    ),
                    style: TextStyle(color: context.adaptiveTextDark),
                    textCapitalization: TextCapitalization.words,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Required' : null,
                  ),
                  const SizedBox(height: 14),

                  // Barangay dropdown
                  DropdownButtonFormField<Barangay>(
                    decoration: InputDecoration(
                      labelText: _isGpsLocked
                          ? 'Location / Barangay (Auto-detected) *'
                          : 'Location / Barangay *',
                      prefixIcon: Icon(
                        _isGpsLocked
                            ? Icons.location_on_outlined
                            : Icons.location_city_outlined,
                        color: _isGpsLocked ? AppColors.darkGreen : null,
                      ),
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: _isGpsLocked
                              ? AppColors.darkGreen
                              : (context.isDarkMode
                                    ? Colors.white
                                    : Colors.grey),
                        ),
                      ),
                    ),
                    dropdownColor: context.adaptiveSurface,
                    style: TextStyle(color: context.adaptiveTextDark),
                    isExpanded: true,
                    hint: _loadingBarangays
                        ? const Text('Loading barangays…')
                        : const Text('Select barangay'),
                    initialValue: _selectedBarangay,
                    items: _barangays.map((b) {
                      return DropdownMenuItem<Barangay>(
                        value: b,
                        child: Text(b.name, overflow: TextOverflow.ellipsis),
                      );
                    }).toList(),
                    onChanged: _loadingBarangays || _fetchingLocation
                        ? null
                        : (val) {
                            final addressNeedsRefresh =
                                _isAddressLocation &&
                                _streetAddressCtrl.text.trim().isNotEmpty;
                            _addressSearchGeneration++;
                            setState(() {
                              _selectedBarangay = val;
                              _isGpsLocked = false;
                              // Clear previously picked coordinates — they
                              // belonged to the old barangay and are no
                              // longer valid for the newly selected one.
                              _latCtrl.clear();
                              _lngCtrl.clear();
                              _resolvedArea = null;
                              _locationTouched = true;
                              _locationConfirmed = false;
                              _isAddressLocation = false;
                              _addressLocationNeedsRefresh =
                                  addressNeedsRefresh;
                              _isBarangayMismatch = false;
                              _isOutsideBoundary = false;
                              _addressCandidates = [];
                              _addressSearchFailure = null;
                              _addressSearchCompleted = false;
                              _searchingAddress = false;
                              _locationMessage = null;
                              _errorMsg = null;
                            });
                            _scheduleAddressSuggestions();
                          },
                    validator: (v) => v == null ? 'Required' : null,
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _streetAddressCtrl,
                    enabled: !_fetchingLocation,
                    textCapitalization: TextCapitalization.words,
                    decoration: InputDecoration(
                      labelText: 'Business address / Street / Purok / Landmark',
                      hintText: 'e.g. 115 Templo Avenue',
                      helperText: _selectedBarangay == null
                          ? null
                          : 'Type at least 5 characters; suggestions appear as you type.',
                      prefixIcon: const Icon(Icons.search_rounded),
                      suffixIcon: _searchingAddress
                          ? const Padding(
                              padding: EdgeInsets.all(12),
                              child: SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                            )
                          : null,
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    onChanged: _onStreetAddressChanged,
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    height: 44,
                    child: OutlinedButton.icon(
                      onPressed: _fetchingLocation
                          ? null
                          : () => _autoFillGps(silent: false),
                      icon: _fetchingLocation
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.my_location_rounded, size: 18),
                      label: Text(
                        _fetchingLocation
                            ? 'Getting location...'
                            : 'Use Current Location',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.darkGreen,
                        side: const BorderSide(color: AppColors.darkGreen),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                    ),
                  ),
                  if (_locationMessage != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      _locationMessage!,
                      style: const TextStyle(
                        color: Colors.orange,
                        fontSize: 12,
                      ),
                    ),
                  ],
                  if (_resolvedArea != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      'Detected: ${_resolvedArea!.barangay}, ${_resolvedArea!.municipality}, ${_resolvedArea!.province}',
                      style: TextStyle(
                        fontSize: 12,
                        color: context.adaptiveTextMid,
                      ),
                    ),
                  ],
                  const SizedBox(height: 14),
                  if (_selectedBarangay == null) ...[
                    const SizedBox(height: 5),
                    const Text(
                      'Address suggestions search across Mataasnakahoy. Choose a result to detect its barangay.',
                      style: TextStyle(fontSize: 12, color: Colors.orange),
                    ),
                  ],
                  if (_addressSearchFailure != null) ...[
                    const SizedBox(height: 8),
                    Text(switch (_addressSearchFailure!) {
                      YellowFlagAddressSearchFailure.offline =>
                        'You are offline. Use Current Location or enter the address manually.',
                      YellowFlagAddressSearchFailure.network =>
                        'Network error while loading suggestions. Use Current Location or enter the address manually.',
                      YellowFlagAddressSearchFailure.unavailable =>
                        'Address search is unavailable. Use Current Location or enter the address manually.',
                    }, style: const TextStyle(color: Colors.red, fontSize: 12)),
                  ],
                  if (!_searchingAddress &&
                      _addressCandidates.isEmpty &&
                      _addressSearchFailure == null &&
                      _addressSearchCompleted &&
                      _streetAddressCtrl.text.trim().isNotEmpty) ...[
                    const SizedBox(height: 8),
                    const Text(
                      'No address suggestions. Try another address or use Current Location.',
                      style: TextStyle(fontSize: 12, color: Colors.orange),
                    ),
                  ],
                  if (_addressCandidates.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      'Choose the matching address. No result is selected automatically.',
                      style: TextStyle(
                        fontSize: 12,
                        color: context.adaptiveTextMid,
                      ),
                    ),
                    ..._addressCandidates.map((candidate) {
                      final selected =
                          _isAddressLocation &&
                          _latCtrl.text ==
                              candidate.latitude.toStringAsFixed(6) &&
                          _lngCtrl.text ==
                              candidate.longitude.toStringAsFixed(6);
                      return Card(
                        margin: const EdgeInsets.only(top: 6),
                        child: ListTile(
                          dense: true,
                          leading: Icon(
                            selected
                                ? Icons.radio_button_checked
                                : Icons.location_on_outlined,
                            color: selected ? AppColors.darkGreen : null,
                          ),
                          title: Text(
                            candidate.formattedAddress,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                          ),
                          subtitle: Text(
                            '${candidate.latitude.toStringAsFixed(6)}, ${candidate.longitude.toStringAsFixed(6)}',
                          ),
                          onTap: () => _selectAddressCandidate(candidate),
                        ),
                      );
                    }),
                  ],
                  if (_addressLocationNeedsRefresh) ...[
                    const SizedBox(height: 8),
                    const Text(
                      'The address or barangay changed. Select a fresh address suggestion or use Current Location before submitting.',
                      style: TextStyle(color: Colors.red, fontSize: 12),
                    ),
                  ],
                  if (_usingLocalBarangayList) ...[
                    const SizedBox(height: 6),
                    const Text(
                      'Offline barangay list · names come from the bundled boundary data; registry IDs will be resolved when syncing.',
                      style: TextStyle(fontSize: 11, color: Colors.orange),
                    ),
                  ],
                  if (_isGpsLocked) ...[
                    const SizedBox(height: 6),
                    const Text(
                      'Barangay auto-detected from the selected location. You can change it in the dropdown.',
                      style: TextStyle(
                        fontSize: 11,
                        color: AppColors.darkGreen,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                  if (!_loadingBarangays) ...[
                    const SizedBox(height: 4),
                    Text(
                      'GPS and selected address locations are checked against the official barangay boundary.',
                      style: TextStyle(
                        fontSize: 11,
                        color: context.adaptiveTextMid,
                      ),
                    ),
                  ],
                  // Notes
                  TextFormField(
                    controller: _notesCtrl,
                    decoration: InputDecoration(
                      labelText: 'Notes (Optional)',
                      hintText: 'Observations, description, landmarks…',
                      prefixIcon: const Icon(Icons.notes_outlined),
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: context.isDarkMode
                              ? Colors.white
                              : Colors.grey,
                        ),
                      ),
                      alignLabelWithHint: true,
                    ),
                    style: TextStyle(color: context.adaptiveTextDark),
                    maxLines: 3,
                    minLines: 2,
                    textCapitalization: TextCapitalization.sentences,
                  ),
                  const SizedBox(height: 22),

                  // Submit button
                  SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _canSubmit
                            ? AppColors.gold
                            : Colors.grey[400],
                        foregroundColor: _canSubmit
                            ? Colors.black87
                            : Colors.white70,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                        elevation: 0,
                      ),
                      onPressed: _canSubmit ? _submit : null,
                      icon: _submitting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                color: Colors.black87,
                                strokeWidth: 2,
                              ),
                            )
                          : const Icon(Icons.flag_rounded, size: 20),
                      label: Text(
                        _submitting ? 'Submitting…' : 'Submit Yellow Flag',
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
