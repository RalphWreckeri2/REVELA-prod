import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class YellowFlagPinPicker extends StatefulWidget {
  const YellowFlagPinPicker({
    super.key,
    required this.initialPosition,
    this.initialSelectedPosition,
  });

  final LatLng initialPosition;
  final LatLng? initialSelectedPosition;

  @override
  State<YellowFlagPinPicker> createState() => _YellowFlagPinPickerState();
}

class _YellowFlagPinPickerState extends State<YellowFlagPinPicker> {
  late LatLng? _selectedPosition = widget.initialSelectedPosition;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.72,
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 16, 20, 12),
              child: Text(
                'Move the pin to the business entrance, then confirm the location.',
                textAlign: TextAlign.center,
              ),
            ),
            Expanded(
              child: GoogleMap(
                initialCameraPosition: CameraPosition(
                  target: widget.initialPosition,
                  zoom: 15,
                ),
                markers: _selectedPosition == null
                    ? const <Marker>{}
                    : {
                        Marker(
                          markerId: const MarkerId('yellow-flag-pin'),
                          position: _selectedPosition!,
                        ),
                      },
                onTap: (position) =>
                    setState(() => _selectedPosition = position),
                myLocationButtonEnabled: false,
                mapToolbarEnabled: false,
                zoomControlsEnabled: true,
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Expanded(
                    child: TextButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('Cancel'),
                    ),
                  ),
                  Expanded(
                    child: FilledButton(
                      onPressed: _selectedPosition == null
                          ? null
                          : () => Navigator.of(context).pop(_selectedPosition),
                      child: const Text('Confirm Pin Location'),
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
