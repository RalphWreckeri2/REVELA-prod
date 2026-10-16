import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../service/boundary_service.dart';
import '../theme/app_theme.dart';
import '../theme/map_styles.dart';

/// Edits a tentative business pin. Only Confirm returns coordinates to the form.
class YellowFlagPinPicker extends StatefulWidget {
  const YellowFlagPinPicker({
    super.key,
    required this.municipalMapView,
    this.initialPin,
  });

  final CameraPosition municipalMapView;
  final LatLng? initialPin;

  @override
  State<YellowFlagPinPicker> createState() => _YellowFlagPinPickerState();
}

class _YellowFlagPinPickerState extends State<YellowFlagPinPicker> {
  final _boundaryService = BoundaryService();
  LatLng? _pin;
  ResolvedAdministrativeArea? _area;
  bool _boundariesReady = false;
  bool _dragging = false;
  bool _confirming = false;

  @override
  void initState() {
    super.initState();
    _pin = widget.initialPin;
    _loadBoundaries();
  }

  Future<void> _loadBoundaries() async {
    await _boundaryService.loadBoundaries();
    if (!mounted) return;
    setState(() {
      _boundariesReady = true;
      _area = _resolvePin();
    });
  }

  ResolvedAdministrativeArea? _resolvePin() {
    final pin = _pin;
    return pin == null
        ? null
        : _boundaryService.resolveAdministrativeArea(
            pin.latitude,
            pin.longitude,
          );
  }

  void _selectPin(LatLng pin) {
    setState(() {
      _pin = pin;
      _dragging = false;
      _area = _resolvePin();
    });
  }

  bool get _canConfirm =>
      _boundariesReady &&
      !_dragging &&
      !_confirming &&
      _pin != null &&
      _area != null;

  void _confirm() {
    // Recheck the actual pin, never the map camera target or device location.
    if (!_canConfirm || _resolvePin() == null) return;
    setState(() => _confirming = true);
    Navigator.of(context).pop(_pin);
  }

  @override
  Widget build(BuildContext context) {
    final pin = _pin;
    final guidance = !_boundariesReady
        ? 'Loading official barangay boundaries…'
        : !_boundaryService.hasLoadedBoundaries
        ? 'Official boundary data is unavailable. Location cannot be verified.'
        : pin == null
        ? 'Tap the map to place the business pin. GPS permission is not needed.'
        : _area == null
        ? 'Coordinates are outside the official Mataasnakahoy barangay boundaries. Move the pin inside the municipality.'
        : 'Business pin: ${_area!.barangay}. Confirm this location to use it in the report.';

    return Scaffold(
      appBar: AppBar(title: const Text('Choose business location')),
      body: Column(
        children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'Tap the business location or drag the pin, then confirm. The pin should mark the business you are reporting.',
            ),
          ),
          Expanded(
            child: GoogleMap(
              initialCameraPosition: pin == null
                  ? widget.municipalMapView
                  : CameraPosition(target: pin, zoom: 17),
              style: context.isDarkMode ? AppMapStyles.darkMapStyle : null,
              // This picker deliberately has no GPS/permission dependency.
              myLocationEnabled: false,
              myLocationButtonEnabled: false,
              mapToolbarEnabled: false,
              onTap: _selectPin,
              markers: {
                if (pin != null)
                  Marker(
                    markerId: const MarkerId('yellow_flag_business_pin'),
                    position: pin,
                    draggable: true,
                    onDragStart: (_) => setState(() => _dragging = true),
                    onDragEnd: _selectPin,
                    infoWindow: const InfoWindow(title: 'Business location'),
                  ),
              },
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    guidance,
                    style: TextStyle(
                      color: _boundariesReady && pin != null && _area == null
                          ? Colors.red
                          : context.adaptiveTextMid,
                    ),
                  ),
                  if (pin != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      '${pin.latitude.toStringAsFixed(6)}, ${pin.longitude.toStringAsFixed(6)}',
                    ),
                  ],
                  const SizedBox(height: 12),
                  ElevatedButton.icon(
                    onPressed: _canConfirm ? _confirm : null,
                    icon: const Icon(Icons.check_rounded),
                    label: const Text('Confirm business location'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
