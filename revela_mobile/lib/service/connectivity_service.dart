import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import 'auth_service.dart';
import 'push_notifications.dart';

/// App-wide connectivity monitor.
///
/// Exposes [isOffline] as a [ValueNotifier] any widget can listen to, and
/// invokes registered listeners exactly once per online → offline transition
/// (debounced) so the app can force-stop the active session and notify the
/// user. Start this once from `main()` — it lives for the app's lifetime.
class ConnectivityService extends ChangeNotifier {
  ConnectivityService._internal();
  static final ConnectivityService instance = ConnectivityService._internal();
  factory ConnectivityService() => instance;

  final Connectivity _connectivity = Connectivity();
  StreamSubscription<List<ConnectivityResult>>? _subscription;
  Timer? _debounce;

  /// True when the device currently has no usable network interface.
  final ValueNotifier<bool> isOffline = ValueNotifier<bool>(false);

  /// Fired once per offline transition (not on every stream event).
  final List<VoidCallback> _offlineListeners = [];

  bool _started = false;

  /// Registers a callback invoked whenever the device goes offline.
  void addOfflineListener(VoidCallback listener) =>
      _offlineListeners.add(listener);

  void removeOfflineListener(VoidCallback listener) =>
      _offlineListeners.remove(listener);

  /// Begins monitoring. Safe to call multiple times — only the first call
  /// subscribes.
  Future<void> start() async {
    if (_started) return;
    _started = true;

    // Seed the initial state so widgets know immediately on cold start.
    try {
      final results = await _connectivity.checkConnectivity();
      _apply(results);
    } catch (e) {
      debugPrint('ConnectivityService: initial check failed: $e');
    }

    _subscription = _connectivity.onConnectivityChanged.listen(
      _scheduleUpdate,
      onError: (Object e) {
        debugPrint('ConnectivityService: stream error: $e');
      },
    );
  }

  Future<void> disposeStream() async {
    await _subscription?.cancel();
    _debounce?.cancel();
    _started = false;
  }

  /// Debounces rapid Wi-Fi/cellular flapping so a momentary blip doesn't
  /// kick the user out of their session.
  void _scheduleUpdate(List<ConnectivityResult> results) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 800), () => _apply(results));
  }

  void _apply(List<ConnectivityResult> results) {
    final bool none =
        results.isEmpty ||
        !results.any((r) => r != ConnectivityResult.none);

    final wasOffline = isOffline.value;
    isOffline.value = none;

    if (none && !wasOffline) {
      debugPrint('ConnectivityService: device went OFFLINE');
      for (final listener in List<VoidCallback>.from(_offlineListeners)) {
        try {
          listener();
        } catch (e) {
          debugPrint('ConnectivityService: offline listener error: $e');
        }
      }
    } else if (!none && wasOffline) {
      debugPrint('ConnectivityService: device back ONLINE');
      // Sync FCM token upon reconnection if user is authenticated
      if (AuthService().isAuthenticated) {
        unawaited(PushNotifications.refreshFcmToken());
      }
    }
  }
}