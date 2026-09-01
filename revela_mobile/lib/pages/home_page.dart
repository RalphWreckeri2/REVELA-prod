import 'dart:async';
import 'dart:ui';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shimmer/shimmer.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:geolocator/geolocator.dart';
import 'package:permission_handler/permission_handler.dart';


import '../component/inspection_card.dart';
import '../component/inspection_modal.dart';

import '../service/assignment_notifications.dart';
import '../service/flag_service.dart';
import '../service/boundary_service.dart';

import '../service/inspection_service.dart';
import '../theme/app_theme.dart';
import '../theme/map_styles.dart';
import 'package:showcaseview/showcaseview.dart';
import 'main_layout.dart';

class HomePage extends StatefulWidget {
  final ValueChanged<bool>? onDrawerToggled;
  const HomePage({super.key, this.onDrawerToggled});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  static const Set<String> _activeStatuses = {'Assigned', 'Reassigned'};

  GoogleMapController? _mapController;
  bool _isDockerExpanded = false;
  bool _isFirstLoad = true;
  String _sortBy = 'newest'; // 'newest' or 'oldest'
  String _dockerTab = 'tasks';
  bool _hasLocationPermission = false;
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
      ..arcToPoint(const Offset(14, 30), radius: const Radius.circular(12), clockwise: false)
      ..lineTo(24, 48)
      ..close();
    canvas.drawPath(path, paint);
    canvas.drawCircle(const Offset(24, 20), 6, Paint()..color = Colors.white);

    final img = await pictureRecorder.endRecording().toImage(48, 48);
    final data = await img.toByteData(format: ImageByteFormat.png);
    if (data != null) {
      _blackMarker = BitmapDescriptor.bytes(data.buffer.asUint8List());
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
      final TextPainter textPainter = TextPainter(textDirection: TextDirection.ltr);
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
        _municipalMarker = BitmapDescriptor.bytes(muniData.buffer.asUint8List());
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
  CameraPosition? _currentCameraPosition;
  static const CameraPosition _initialCamera = CameraPosition(
    target: LatLng(13.9667, 121.1167),
    zoom: 12,
  );

  // ── Real data ──────────────────────────────────────────────────────────────
  List<InspectionTask> _tasks = [];
  bool _loadingTasks = true;
  String? _taskError;

  /// Yellow flags submitted by this inspector (shown as extra map markers).
  List<MyFlag> _myFlags = [];



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
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _fetchTasks(silent: true);
    }
  }

  Future<void> _primePermissionsAndFetch() async {
    await Permission.locationWhenInUse.request();
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
    try {
      final flags = await FlagService().fetchMyYellowFlags();
      if (mounted) setState(() => _myFlags = flags);
    } catch (e) {
      debugPrint('_fetchMyFlags: $e');
    }
  }

  void _syncMapToTasks() {
    if (_mapController == null) return;
    final withCoords = _tasks
        .where((t) => t.latitude != null && t.longitude != null)
        .toList();
    if (withCoords.isEmpty) return;
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

    // ── Municipality Hall Marker ─────────────────────────────────────────────
    markers.add(
      Marker(
        markerId: const MarkerId('mataasnakahoy_municipal_hall'),
        position: const LatLng(13.960416, 121.114547),
        infoWindow: const InfoWindow(
          title: 'Mataasnakahoy Municipal Hall',
          snippet: 'Center of operations',
        ),
        icon: _municipalMarker ?? BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueAzure),
      ),
    );

    // ── Assignment-task markers (pinned by the system) ──────────────────
    for (final t in _tasks) {
      if (t.latitude == null || t.longitude == null) continue;
      final icon = t.flagColor == 'Black' && _blackMarker != null
          ? _blackMarker!
          : BitmapDescriptor.defaultMarkerWithHue(switch (t.flagColor) {
              'Red' => BitmapDescriptor.hueRed,
              'Yellow' => BitmapDescriptor.hueYellow,
              'Orange' => 15.0,  // deep orange hue — distinct from hueYellow (60) and hueOrange (30)
              'Purple' => BitmapDescriptor.hueViolet, // 270.0 degrees - purple
              _ => BitmapDescriptor.hueGreen,
            });
      markers.add(
        Marker(
          markerId: MarkerId('flag_${t.logID}'),
          position: LatLng(t.latitude!, t.longitude!),
          infoWindow: InfoWindow(
            title: t.detectedName,
            snippet: '${t.barangayName} · ${t.flagColor}',
          ),
          icon: icon,
          onTap: () => _onTaskTap(t),
        ),
      );
    }

    // ── Inspector-reported yellow flag markers ──────────────────────────
    // These are flags this inspector submitted via the "Flag Business" button.
    // Show a "You flagged" snippet so the inspector knows it's their own submission.
    for (final f in _myFlags) {
      // Skip if this flag is already shown as an assigned task.
      if (_tasks.any((t) => t.logID == f.logID)) continue;

      // Skip if it has been acted upon (resolved/completed)
      final isActiveOrUnassigned = f.verificationStatus == null ||
          const {'Assigned', 'Reassigned'}.contains(f.verificationStatus);
      if (!isActiveOrUnassigned) continue;

      // Skip if it was resolved to Green by admin without inspection
      if (f.flagColor == 'Green') continue;

      markers.add(
        Marker(
          markerId: MarkerId('my_flag_${f.logID}'),
          position: LatLng(f.lat, f.lng),
          infoWindow: InfoWindow(
            title: f.detectedName,
            snippet: 'You flagged this • ${f.flagColor}',
          ),
          icon: BitmapDescriptor.defaultMarkerWithHue(
            BitmapDescriptor.hueYellow,
          ),
          onTap: () => _onYellowFlagTap(f),
        ),
      );
    }

    return markers;
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
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) return;

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        return;
      }

      if (mounted) {
        setState(() => _hasLocationPermission = true);
      }

      final position = await Geolocator.getCurrentPosition();
      await _mapController?.animateCamera(
        CameraUpdate.newCameraPosition(
          CameraPosition(
            target: LatLng(position.latitude, position.longitude),
            zoom: 16,
          ),
        ),
      );
    } catch (e) {
      debugPrint('Error getting location: $e');
    }
  }

  // ── Open inspection modal ─────────────────────────────────────────────────
  void _onTaskTap(InspectionTask task) async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) =>
          InspectionModal(task: task, onSubmitted: () => _fetchTasks()),
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
            child: Image.asset(
              'assets/images/standing.png',
              height: 240,
            ),
          ),
          Container(
            margin: const EdgeInsets.only(top: 110),
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: context.adaptiveSurface,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
            ),
            child: SafeArea(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Reported Flag', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: context.adaptiveTextDark)),
                  const SizedBox(height: 16),
                  _buildDetailRow('Business Name', flag.detectedName),
                  _buildDetailRow('Color', flag.flagColor),
                  _buildDetailRow('Status', flag.verificationStatus ?? 'Pending'),
                  if (flag.notes != null && flag.notes!.isNotEmpty)
                    _buildDetailRow('Notes', flag.notes!),
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.gold.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: AppColors.gold.withValues(alpha: 0.3)),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.info_outline_rounded, color: AppColors.gold, size: 20),
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
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      child: const Text('Close', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
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
            child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600, color: Colors.grey)),
          ),
          Expanded(
            child: Text(value, style: TextStyle(fontWeight: FontWeight.w600, color: context.adaptiveTextDark)),
          ),
        ],
      ),
    );
  }

  // ── Open yellow flag sheet ────────────────────────────────────────────────
  void _showYellowFlagSheet() async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);
    double? defaultLat;
    double? defaultLng;
    try {
      final pos = await Geolocator.getLastKnownPosition();
      defaultLat = pos?.latitude;
      defaultLng = pos?.longitude;
    } catch (_) {}
    if (!mounted) return;

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _YellowFlagSheet(
        defaultLat: defaultLat,
        defaultLng: defaultLng,
        onSuccess: (MyFlag newFlag) {
          if (!mounted) return;
          // Optimistically add the new flag to the map before the next poll.
          setState(() {
            if (!_myFlags.any((f) => f.logID == newFlag.logID)) {
              _myFlags = [..._myFlags, newFlag];
            }
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
        border: Border.all(color: context.isDarkMode ? Colors.white24 : Colors.black12),
        boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 8, offset: Offset(0, 4))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Map Legend', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: context.adaptiveTextDark)),
              const SizedBox(width: 24),
              GestureDetector(
                onTap: () => setState(() => _isLegendOpen = false),
                child: Icon(Icons.close, size: 16, color: context.adaptiveTextMid),
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
          Text(label, style: TextStyle(fontSize: 12, color: context.adaptiveTextDark)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final screenHeight = MediaQuery.of(context).size.height;
    final paddingTop = MediaQuery.of(context).padding.top;

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
              description: 'Tap this to see what the different colored map markers represent.',
              targetPadding: const EdgeInsets.all(4),
              child: FloatingActionButton(
                mini: true,
                backgroundColor: context.isDarkMode ? Colors.black : Colors.white,
                heroTag: 'legend_toggle',
                onPressed: () => setState(() => _isLegendOpen = !_isLegendOpen),
                child: Icon(Icons.legend_toggle_rounded, color: context.isDarkMode ? Colors.white : AppColors.darkGreen),
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
                        color: context.isDarkMode ? Colors.white : AppColors.darkGreen,
                      ),
                    )
                  : Icon(Icons.refresh, color: context.isDarkMode ? Colors.white : AppColors.darkGreen),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          // ── 1. Google Map ────────────────────────────────────────────────
          Positioned.fill(
            child: GoogleMap(style: context.isDarkMode ? AppMapStyles.darkMapStyle : "[]",
              padding: EdgeInsets.only(
                bottom: _isDockerExpanded ? screenHeight * 0.5 : 0.0,
              ),
              initialCameraPosition: _initialCamera,
              mapType: _currentMapType,
              markers: _buildFlagMarkers(),
              onCameraMove: (position) {
                _currentCameraPosition = position;
              },
              onMapCreated: (controller) async {
                _mapController = controller;
                
                await _goToCurrentLocation();
                _syncMapToTasks();
              },
              myLocationEnabled: _hasLocationPermission,
              myLocationButtonEnabled: false,
              zoomControlsEnabled: false,
              mapToolbarEnabled: false,
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
              description: 'Use these to zoom, center on your location, or toggle 3D view.',
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
                  tooltip: 'Recenter',
                  active: false,
                  onTap: () {
                    _goToCurrentLocation();
                  },
                ),
                const SizedBox(height: 6),
                _MapControlButton(
                  icon: _currentMapType == MapType.normal ? Icons.satellite_alt_rounded : Icons.map_rounded,
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
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
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
                        padding: const EdgeInsets.symmetric(vertical: 14),
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
                            // Header row
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Expanded(
                                  child: _isFirstLoad ? Text(
                                    "Saan ang Sinsay?",
                                    style: TextStyle(
                                      fontSize: 20,
                                      fontWeight: FontWeight.bold,
                                      color: context.adaptiveTextDark,
                                    ),
                                  ) : Row(
                                    children: [
                                      GestureDetector(
                                        onTap: () => setState(() => _dockerTab = 'tasks'),
                                        child: Text(
                                          "Tasks",
                                          style: TextStyle(
                                            fontSize: 20,
                                            fontWeight: FontWeight.bold,
                                            color: _dockerTab == 'tasks' ? context.adaptiveTextDark : Colors.grey,
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
                                            color: _dockerTab == 'flags' ? context.adaptiveTextDark : Colors.grey,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                // Task count badge
                                if (!_loadingTasks && (_dockerTab == 'tasks' ? _tasks.isNotEmpty : _myFlags.isNotEmpty))
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 10,
                                      vertical: 4,
                                    ),
                                    decoration: BoxDecoration(
                                      color: context.isDarkMode ? Colors.black : AppColors.darkGreen.withValues(alpha: 
                                        0.1,
                                      ),
                                      borderRadius: BorderRadius.circular(12),
                                    ),
                                    child: Text(
                                      _dockerTab == 'tasks' ? '${_tasks.length} task${_tasks.length != 1 ? 's' : ''}' : '${_myFlags.length} flag${_myFlags.length != 1 ? 's' : ''}',
                                      style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                        color: context.isDarkMode ? Colors.white : AppColors.darkGreen,
                                      ),
                                    ),
                                  ),
                                // Sort toggle
                                if (!_loadingTasks && _tasks.isNotEmpty) ...[
                                  const SizedBox(width: 8),
                                  GestureDetector(
                                    onTap: () => setState(
                                      () => _sortBy = _sortBy == 'newest'
                                          ? 'oldest'
                                          : 'newest',
                                    ),
                                    child: Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 10,
                                        vertical: 4,
                                      ),
                                      decoration: BoxDecoration(
                                        color: context.isDarkMode ? Colors.black : const Color(0xFFF1F5F9),
                                        borderRadius: BorderRadius.circular(12),
                                        border: Border.all(color: context.isDarkMode ? Colors.white : Colors.transparent),
                                      ),
                                      child: Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(
                                            _sortBy == 'newest'
                                                ? Icons.arrow_downward_rounded
                                                : Icons.arrow_upward_rounded,
                                            size: 12,
                                            color: context.isDarkMode ? Colors.white : const Color(0xFF64748B),
                                          ),
                                          const SizedBox(width: 4),
                                          Text(
                                            _sortBy == 'newest'
                                                ? 'Newest'
                                                : 'Oldest',
                                            style: TextStyle(
                                              fontSize: 11,
                                              fontWeight: FontWeight.w600,
                                              color: context.isDarkMode ? Colors.white : const Color(0xFF64748B),
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ],
                                IconButton(
                                  icon: Icon(Icons.close_rounded, color: context.adaptiveTextDark),
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
                                          padding: const EdgeInsets.symmetric(vertical: 32),
                                          child: Center(
                                            child: Column(
                                              mainAxisSize: MainAxisSize.min,
                                              children: [
                                                Icon(Icons.flag_outlined, color: Colors.grey[400], size: 48),
                                                const SizedBox(height: 12),
                                                Text('No yellow flags submitted yet.', style: TextStyle(color: Colors.grey[500], fontSize: 14)),
                                              ],
                                            ),
                                          ),
                                        )
                                      : RefreshIndicator(
                                          color: AppColors.gold,
                                          onRefresh: () => _fetchMyFlags(),
                                          child: ListView.builder(
                                            shrinkWrap: true,
                                            padding: EdgeInsets.zero,
                                            physics: const AlwaysScrollableScrollPhysics(),
                                            itemCount: _myFlags.length,
                                            itemBuilder: (context, index) {
                                              final f = _myFlags[_myFlags.length - 1 - index]; // reverse chronological
                                              return GestureDetector(
                                                onTap: () => _onYellowFlagTap(f),
                                                child: Container(
                                                  margin: const EdgeInsets.only(bottom: 12),
                                                  padding: const EdgeInsets.all(16),
                                                  decoration: BoxDecoration(
                                                    color: context.isDarkMode ? Colors.grey[900] : Colors.white,
                                                    borderRadius: BorderRadius.circular(16),
                                                    border: Border.all(color: context.isDarkMode ? Colors.grey[800]! : Colors.grey[200]!),
                                                  ),
                                                  child: Row(
                                                    children: [
                                                      Container(
                                                        padding: const EdgeInsets.all(10),
                                                        decoration: BoxDecoration(color: AppColors.gold.withValues(alpha: 0.1), shape: BoxShape.circle),
                                                        child: const Icon(Icons.flag_rounded, color: AppColors.gold, size: 20),
                                                      ),
                                                      const SizedBox(width: 16),
                                                      Expanded(
                                                        child: Column(
                                                          crossAxisAlignment: CrossAxisAlignment.start,
                                                          children: [
                                                            Text(f.detectedName, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: context.adaptiveTextDark)),
                                                            const SizedBox(height: 4),
                                                            Text(f.verificationStatus ?? 'Pending', style: TextStyle(color: Colors.grey[500], fontSize: 12)),
                                                          ],
                                                        ),
                                                      ),
                                                      const Icon(Icons.chevron_right_rounded, color: Colors.grey),
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
                                          physics: const NeverScrollableScrollPhysics(),
                                          itemCount: 3,
                                          padding: EdgeInsets.zero,
                                          itemBuilder: (context, index) => Padding(
                                            padding: const EdgeInsets.only(bottom: 12.0),
                                            child: Shimmer.fromColors(
                                              baseColor: context.isDarkMode ? Colors.grey[800]! : Colors.grey[300]!,
                                              highlightColor: context.isDarkMode ? Colors.grey[700]! : Colors.grey[100]!,
                                              child: Container(
                                                height: 120,
                                                decoration: BoxDecoration(
                                                  color: Colors.white,
                                                  borderRadius: BorderRadius.circular(16),
                                                ),
                                              ),
                                            ),
                                          ),
                                        )
                                      : _taskError != null
                                      ? Padding(
                                          padding: const EdgeInsets.symmetric(vertical: 32),
                                          child: Center(
                                            child: Column(
                                              mainAxisSize: MainAxisSize.min,
                                              children: [
                                                const Icon(Icons.wifi_off, color: Colors.grey, size: 40),
                                                const SizedBox(height: 12),
                                                Text(_taskError!, style: const TextStyle(color: Colors.grey)),
                                                const SizedBox(height: 12),
                                                TextButton(onPressed: _fetchTasks, child: const Text('Retry')),
                                              ],
                                            ),
                                          ),
                                        )
                                      : _tasks.isEmpty
                                      ? Padding(
                                          padding: const EdgeInsets.symmetric(vertical: 32),
                                          child: Center(
                                            child: Column(
                                              mainAxisSize: MainAxisSize.min,
                                              children: [
                                                Icon(Icons.check_circle_outline, color: Colors.grey[400], size: 48),
                                                const SizedBox(height: 12),
                                                Text('No assignments yet.', style: TextStyle(color: Colors.grey[500], fontSize: 14)),
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
                                            physics: const AlwaysScrollableScrollPhysics(),
                                            itemCount: _sortedTasks.length,
                                            itemBuilder: (context, index) =>
                                                InspectionCard(
                                                  task: _sortedTasks[index],
                                                  onTap: () => _onTaskTap(_sortedTasks[index]),
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
                      color: context.isDarkMode ? Colors.white24 : Colors.black12,
                    ),
                  ),
                  child: Column(
                    children: [
                      Showcase(
                        key: MainLayout.mapAssignmentsBtnTourKey,
                        title: 'Tasks Menu',
                        description: 'Swipe up or tap here to view and manage your inspection assignments.',
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
                        color: context.isDarkMode ? Colors.white24 : Colors.black12,
                      ),
                      Showcase(
                        key: MainLayout.mapAddFlagBtnTourKey,
                        title: 'Add Yellow Flag',
                        description: 'Notice an unregistered business? Tap here to flag it directly from the map.',
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
              BoxShadow(blurRadius: 6, color: Colors.black.withValues(alpha: 0.12)),
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
  final double? defaultLat;
  final double? defaultLng;
  final void Function(MyFlag) onSuccess;

  const _YellowFlagSheet({
    this.defaultLat,
    this.defaultLng,
    required this.onSuccess,
  });

  @override
  State<_YellowFlagSheet> createState() => _YellowFlagSheetState();
}

class _YellowFlagSheetState extends State<_YellowFlagSheet> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _latCtrl = TextEditingController();
  final _lngCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();

  final FlagService _flagService = FlagService();
  final BoundaryService _boundaryService = BoundaryService();

  List<Barangay> _barangays = [];
  Barangay? _selectedBarangay;
  bool _loadingBarangays = true;
  bool _fetchingLocation = false;
  bool _submitting = false;
  bool _isOutsideBoundary = false;
  String? _errorMsg;

  // True once the user has interacted with location in any way (pressed
  // "Use Current Location" or changed barangay). Guards against the slow,
  // silent GPS fetch kicked off in initState resolving *after* the user
  // has already made their own choice and stomping it back.
  bool _locationTouched = false;

  bool get _canSubmit =>
      !_submitting &&
      !_isOutsideBoundary &&
      _selectedBarangay != null &&
      _latCtrl.text.isNotEmpty &&
      _lngCtrl.text.isNotEmpty;

  @override
  void initState() {
    super.initState();
    _latCtrl.text = widget.defaultLat?.toStringAsFixed(6) ?? '';
    _lngCtrl.text = widget.defaultLng?.toStringAsFixed(6) ?? '';
    _boundaryService.loadBoundaries();
    _loadBarangays();
    _autoFillGps(silent: true);
  }

  Future<void> _applyCoordinates(double lat, double lng, {bool silent = false, bool isMock = false}) async {
    await _boundaryService.loadBoundaries();

    final insideMataasnakahoy = _boundaryService.isPointInMataasnakahoy(lat, lng);

    if (!insideMataasnakahoy) {
      if (!mounted) return;
      setState(() {
        _latCtrl.text = lat.toStringAsFixed(6);
        _lngCtrl.text = lng.toStringAsFixed(6);
        _selectedBarangay = null; // Clear/Reset Barangay dropdown
        _locationTouched = true;
        _isOutsideBoundary = true;
        _errorMsg = 'Location is outside the Municipality of Mataasnakahoy.';
      });

      if (!silent && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Location is outside the Municipality of Mataasnakahoy.'),
            backgroundColor: Colors.red,
            behavior: SnackBarBehavior.floating,
            duration: Duration(seconds: 4),
          ),
        );
      }
      return;
    }

    Barangay? matched;
    if (_barangays.isNotEmpty) {
      matched = _boundaryService.findBarangayForPoint(lat, lng, _barangays);
    }

    if (!mounted) return;
    setState(() {
      _latCtrl.text = lat.toStringAsFixed(6);
      _lngCtrl.text = lng.toStringAsFixed(6);
      _selectedBarangay = matched; // Auto-populate matched barangay
      _locationTouched = true;
      _isOutsideBoundary = false;
      _errorMsg = null;
    });

    if (!silent && mounted) {
      final msg = isMock
          ? 'Mock location set: ${matched?.name ?? "Mataasnakahoy"} (13.9634, 121.1143)'
          : (matched != null
              ? 'Location set to ${matched.name} (Mataasnakahoy)'
              : 'Current location inside Mataasnakahoy. Please confirm barangay.');
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

  Future<void> _autoFillGps({bool silent = false}) async {
    if (_fetchingLocation) return;
    setState(() => _fetchingLocation = true);
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 6),
        ),
      );
      if (!mounted) return;
      if (silent && _locationTouched) {
        setState(() => _fetchingLocation = false);
        return;
      }

      await _applyCoordinates(pos.latitude, pos.longitude, silent: silent);
      if (mounted) setState(() => _fetchingLocation = false);
    } catch (_) {
      if (mounted) {
        setState(() => _fetchingLocation = false);
        if (!silent) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Could not fetch current location. Please check GPS settings.'),
              backgroundColor: Colors.red,
              behavior: SnackBarBehavior.floating,
            ),
          );
        }
      }
    }
  }

  Future<void> _useMockLocation() async {
    if (_fetchingLocation) return;
    setState(() => _fetchingLocation = true);
    const mockLat = 13.9634;
    const mockLng = 121.1143;
    await _applyCoordinates(mockLat, mockLng, silent: false, isMock: true);
    if (mounted) setState(() => _fetchingLocation = false);
  }

  Future<void> _loadBarangays() async {
    try {
      final list = await _flagService.fetchBarangays();
      if (mounted) {
        await _boundaryService.loadBoundaries();
        Barangay? matched;
        if (_latCtrl.text.isNotEmpty && _lngCtrl.text.isNotEmpty) {
          final lat = double.tryParse(_latCtrl.text);
          final lng = double.tryParse(_lngCtrl.text);
          if (lat != null && lng != null && _boundaryService.isPointInMataasnakahoy(lat, lng)) {
            matched = _boundaryService.findBarangayForPoint(lat, lng, list);
          }
        }
        setState(() {
          _barangays = list;
          _loadingBarangays = false;
          if (_selectedBarangay == null && matched != null) {
            _selectedBarangay = matched;
            _isOutsideBoundary = false;
          }
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadingBarangays = false;
          _errorMsg = 'Could not load barangays. Check connection.';
        });
      }
    }
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

    if (!_boundaryService.isPointInMataasnakahoy(lat, lng)) {
      setState(() => _errorMsg = 'Location is outside the Municipality of Mataasnakahoy.');
      return;
    }

    if (!_boundaryService.isPointInBarangay(lat, lng, _selectedBarangay!.name)) {
      setState(() => _errorMsg = 'The selected coordinates are outside the boundaries of ${_selectedBarangay!.name}.');
      return;
    }

    setState(() {
      _submitting = true;
      _errorMsg = null;
    });

    try {
      final newFlag = await _flagService.reportYellowFlag(
        businessName: _nameCtrl.text.trim(),
        lat: lat,
        lng: lng,
        barangayID: _selectedBarangay!.id,
        notes: _notesCtrl.text.trim().isEmpty ? null : _notesCtrl.text.trim(),
      );

      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onSuccess(newFlag);
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
    _nameCtrl.dispose();
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
                        borderSide: BorderSide(color: context.isDarkMode ? Colors.white : Colors.grey),
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
                      labelText: 'Barangay *',
                      prefixIcon: const Icon(Icons.location_city_outlined),
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(color: context.isDarkMode ? Colors.white : Colors.grey),
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
                    onChanged: _loadingBarangays
                        ? null
                        : (val) => setState(() {
                            _selectedBarangay = val;
                            // Clear previously picked coordinates — they
                            // belonged to the old barangay and are no
                            // longer valid for the newly selected one.
                            _latCtrl.clear();
                            _lngCtrl.clear();
                            _locationTouched = true;
                            _errorMsg = null;
                          }),
                    validator: (v) => v == null ? 'Required' : null,
                  ),
                  const SizedBox(height: 14),

                  // Location section
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: context.isDarkMode ? Colors.black : Colors.grey[50],
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: context.isDarkMode ? Colors.white : Colors.grey.shade300),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.location_on_rounded,
                              color: AppColors.darkGreen,
                              size: 18,
                            ),
                            const SizedBox(width: 8),
                            const Text(
                              'Location *',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: AppColors.darkGreen,
                              ),
                            ),
                            if (_fetchingLocation) ...[
                              const SizedBox(width: 8),
                              const SizedBox(
                                width: 12,
                                height: 12,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: AppColors.darkGreen,
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 10),
                        if (_latCtrl.text.isEmpty)
                          const Text(
                            'No location selected',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.grey,
                              fontStyle: FontStyle.italic,
                            ),
                          )
                        else
                          Text(
                            'Lat: ${_latCtrl.text}, Lng: ${_lngCtrl.text}',
                            style: TextStyle(
                              fontSize: 12,
                              color: context.adaptiveTextDark,
                              fontFamily: 'Courier',
                            ),
                          ),
                        const SizedBox(height: 10),
                        SizedBox(
                          width: double.infinity,
                          height: 44,
                          child: OutlinedButton.icon(
                            onPressed: _fetchingLocation ? null : () => _autoFillGps(silent: false),
                            icon: const Icon(
                              Icons.my_location_rounded,
                              size: 18,
                            ),
                            label: Text(
                              _fetchingLocation ? 'Getting location...' : 'Use Current Location',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: AppColors.darkGreen,
                              side: const BorderSide(
                                color: AppColors.darkGreen,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(10),
                              ),
                            ),
                          ),
                        ),
                        if (kDebugMode) ...[
                          const SizedBox(height: 8),
                          SizedBox(
                            width: double.infinity,
                            height: 38,
                            child: OutlinedButton.icon(
                              onPressed: _fetchingLocation ? null : _useMockLocation,
                              icon: const Icon(
                                Icons.bug_report_rounded,
                                size: 16,
                                color: AppColors.gold,
                              ),
                              label: const Text(
                                'Mock Mataasnakahoy GPS (13.9634, 121.1143)',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.gold,
                                ),
                              ),
                              style: OutlinedButton.styleFrom(
                                side: const BorderSide(color: AppColors.gold),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(10),
                                ),
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),

                  // Notes
                  TextFormField(
                    controller: _notesCtrl,
                    decoration: InputDecoration(
                      labelText: 'Notes (optional)',
                      hintText: 'Observations, description, landmarks…',
                      prefixIcon: const Icon(Icons.notes_outlined),
                      filled: context.isDarkMode,
                      fillColor: context.isDarkMode ? Colors.black : null,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(color: context.isDarkMode ? Colors.white : Colors.grey),
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
                        backgroundColor: _canSubmit ? AppColors.gold : Colors.grey[400],
                        foregroundColor: _canSubmit ? Colors.black87 : Colors.white70,
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


