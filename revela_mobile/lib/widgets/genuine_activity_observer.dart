import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../service/auth_service.dart';

class GenuineActivityObserver extends StatefulWidget {
  const GenuineActivityObserver({
    required this.authService,
    required this.child,
    super.key,
  });

  final AuthService authService;
  final Widget child;

  @override
  State<GenuineActivityObserver> createState() =>
      _GenuineActivityObserverState();
}

class _GenuineActivityObserverState extends State<GenuineActivityObserver>
    with WidgetsBindingObserver {
  static const _heartbeatInterval = Duration(seconds: 20);

  bool _isForeground = false;
  Timer? _heartbeatTimer;

  @override
  void initState() {
    super.initState();
    _isForeground =
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    WidgetsBinding.instance.addObserver(this);
    HardwareKeyboard.instance.addHandler(_handleKeyEvent);
    if (_isForeground) _startForegroundHeartbeat();
  }

  @override
  void dispose() {
    _heartbeatTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    HardwareKeyboard.instance.removeHandler(_handleKeyEvent);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _isForeground = state == AppLifecycleState.resumed;
    if (_isForeground) {
      _startForegroundHeartbeat();
    } else {
      _heartbeatTimer?.cancel();
      _heartbeatTimer = null;
    }
  }

  void _startForegroundHeartbeat() {
    _heartbeatTimer?.cancel();
    _reportHeartbeat();
    _heartbeatTimer = Timer.periodic(
      _heartbeatInterval,
      (_) => _reportHeartbeat(),
    );
  }

  void _reportHeartbeat() {
    if (!_isForeground || !widget.authService.isAuthenticated) return;
    unawaited(widget.authService.reportForegroundSessionHeartbeat());
  }

  bool _handleKeyEvent(KeyEvent event) {
    if (event is KeyDownEvent) _reportActivity();
    return false;
  }

  void _reportActivity() {
    if (!_isForeground || !widget.authService.isAuthenticated) return;
    unawaited(widget.authService.reportGenuineUserActivity());
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) => _reportActivity(),
      child: widget.child,
    );
  }
}
