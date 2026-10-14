import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../service/connectivity_service.dart';

class StreetViewScreen extends StatefulWidget {
  const StreetViewScreen({required this.position, super.key});

  final LatLng position;

  @override
  State<StreetViewScreen> createState() => _StreetViewScreenState();
}

class _StreetViewScreenState extends State<StreetViewScreen>
    with WidgetsBindingObserver {
  static const _viewType = 'revela/streetview-panorama';
  static const _loadTimeout = Duration(seconds: 20);

  StreamSubscription<dynamic>? _panoramaSubscription;
  Timer? _loadTimer;
  MethodChannel? _viewChannel;
  String _status = 'loading';
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    ConnectivityService.instance.isOffline.addListener(_onConnectivityChanged);
    unawaited(_checkConnectivity());
  }

  Future<void> _checkConnectivity() async {
    if (ConnectivityService.instance.isOffline.value) {
      if (mounted) setState(() => _offline = true);
      return;
    }
    try {
      final results = await Connectivity().checkConnectivity();
      if (!mounted) return;
      final offline =
          results.isEmpty ||
          !results.any((result) => result != ConnectivityResult.none);
      setState(() => _offline = offline);
      if (!offline) _startLoadTimer();
    } on Exception catch (error) {
      debugPrint('Could not check connectivity for Street View: $error');
      if (mounted) {
        setState(() {
          _offline = false;
          _status = 'network-error';
        });
      }
    }
  }

  void _onConnectivityChanged() {
    final offline = ConnectivityService.instance.isOffline.value;
    if (!mounted || offline == _offline) return;
    setState(() {
      _offline = offline;
      if (offline) _status = 'offline';
    });
    if (offline) {
      _loadTimer?.cancel();
      _viewChannel?.invokeMethod<void>('pause').catchError((Object error) {
        debugPrint('Could not pause Street View while offline: $error');
      });
    } else {
      unawaited(_retry());
    }
  }

  void _startLoadTimer() {
    _loadTimer?.cancel();
    _loadTimer = Timer(_loadTimeout, () {
      if (mounted && _status == 'loading') {
        setState(() => _status = 'network-error');
      }
    });
  }

  void _onPlatformViewCreated(int id) {
    final channelName = 'revela/streetview/$id';
    _viewChannel = MethodChannel(channelName);
    _panoramaSubscription = EventChannel('$channelName/events')
        .receiveBroadcastStream()
        .listen(
          _onPanoramaEvent,
          onError: (Object error) {
            debugPrint('Street View platform stream failed: $error');
            if (mounted) setState(() => _status = 'network-error');
          },
        );
    final lifecycleMethod = _offline ? 'pause' : 'resume';
    _viewChannel!.invokeMethod<void>(lifecycleMethod).catchError((
      Object error,
    ) {
      debugPrint('Could not $lifecycleMethod Street View panorama: $error');
    });
    if (!_offline) _startLoadTimer();
  }

  void _onPanoramaEvent(dynamic event) {
    if (!mounted || event is! Map) return;
    final state = event['state'];
    if (state is! String) return;
    _loadTimer?.cancel();
    setState(() => _status = state);
    if (state == 'loading') _startLoadTimer();
  }

  Future<void> _retry() async {
    List<ConnectivityResult> connectivity;
    try {
      connectivity = await Connectivity().checkConnectivity();
    } on Exception catch (error) {
      debugPrint(
        'Could not check connectivity before Street View retry: $error',
      );
      if (mounted) setState(() => _status = 'network-error');
      return;
    }
    final offline =
        connectivity.isEmpty ||
        !connectivity.any((result) => result != ConnectivityResult.none);
    if (!mounted) return;
    if (offline) {
      setState(() {
        _offline = true;
        _status = 'offline';
      });
      return;
    }

    setState(() {
      _offline = false;
      _status = 'loading';
    });
    _startLoadTimer();
    try {
      await _viewChannel?.invokeMethod<void>('retry');
    } on PlatformException catch (error) {
      debugPrint('Street View retry failed: ${error.message}');
      if (mounted) setState(() => _status = 'network-error');
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final channel = _viewChannel;
    if (channel == null) return;
    final shouldResume = state == AppLifecycleState.resumed && !_offline;
    final method = shouldResume ? 'resume' : 'pause';
    channel.invokeMethod<void>(method).catchError((Object error) {
      debugPrint('Could not $method Street View panorama: $error');
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    ConnectivityService.instance.isOffline.removeListener(
      _onConnectivityChanged,
    );
    _loadTimer?.cancel();
    _panoramaSubscription?.cancel();
    _viewChannel?.invokeMethod<void>('pause').catchError((Object error) {
      debugPrint('Could not pause Street View panorama during dispose: $error');
    });
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isAndroid = defaultTargetPlatform == TargetPlatform.android;
    final isAvailable = _status == 'available';
    final isOffline = _offline || _status == 'offline';
    final isUnavailable = _status == 'unavailable';
    final hasError = _status == 'network-error';

    return Scaffold(
      appBar: AppBar(
        title: Text(isAvailable ? 'Nearby Street View' : 'Street View'),
        leading: IconButton(
          tooltip: 'Back to Map',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ),
      body: !isAndroid
          ? _message(
              context,
              'Street View is currently available on Android only.',
              showRetry: false,
            )
          : Stack(
              children: [
                Positioned.fill(
                  child: AndroidView(
                    viewType: _viewType,
                    creationParams: {
                      'latitude': widget.position.latitude,
                      'longitude': widget.position.longitude,
                    },
                    creationParamsCodec: const StandardMessageCodec(),
                    onPlatformViewCreated: _onPlatformViewCreated,
                  ),
                ),
                if (_status == 'loading' && !isOffline)
                  Positioned.fill(
                    child: ColoredBox(
                      color: Theme.of(context).scaffoldBackgroundColor,
                      child: const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            CircularProgressIndicator(),
                            SizedBox(height: 14),
                            Text('Looking for nearby Street View imagery…'),
                          ],
                        ),
                      ),
                    ),
                  ),
                if (isOffline)
                  _message(
                    context,
                    'Street View needs an internet connection.',
                    showRetry: true,
                  ),
                if (isUnavailable)
                  _message(
                    context,
                    'Street View is unavailable for this location.',
                    showRetry: false,
                  ),
                if (hasError)
                  _message(
                    context,
                    'Street View could not load. Check your connection and try again.',
                    showRetry: true,
                  ),
                if (isAvailable)
                  Positioned(
                    left: 12,
                    right: 12,
                    bottom: 12,
                    child: SafeArea(
                      child: Material(
                        color: Theme.of(
                          context,
                        ).colorScheme.surface.withValues(alpha: 0.94),
                        borderRadius: BorderRadius.circular(12),
                        child: const Padding(
                          padding: EdgeInsets.all(12),
                          child: Text(
                            'Street View imagery may not reflect current conditions. This nearby view may not show the exact business entrance.',
                            textAlign: TextAlign.center,
                            style: TextStyle(fontSize: 12, height: 1.35),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
    );
  }

  Widget _message(
    BuildContext context,
    String message, {
    required bool showRetry,
  }) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              showRetry ? Icons.wifi_off_rounded : Icons.streetview_rounded,
              size: 42,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 16),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 18),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 12,
              children: [
                if (showRetry)
                  OutlinedButton.icon(
                    onPressed: _retry,
                    icon: const Icon(Icons.refresh_rounded),
                    label: const Text('Retry'),
                  ),
                FilledButton.icon(
                  onPressed: () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.map_outlined),
                  label: const Text('Back to Map'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
