import 'dart:ui';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'theme/app_theme.dart';
import 'pages/splash_screen.dart';
import 'pages/login_page.dart';
import 'pages/main_layout.dart';
import 'service/auth_service.dart';
import 'service/connectivity_service.dart';
import 'service/push_notifications.dart';

final ValueNotifier<ThemeMode> themeModeNotifier = ValueNotifier<ThemeMode>(
  ThemeMode.system,
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Firebase configuration can be absent in a local/dev build. Push is
  // optional, so never let its initialization prevent the Flutter UI from
  // reaching runApp().
  try {
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
    await PushNotifications.initialize();
  } catch (error, stackTrace) {
    debugPrint('[FIREBASE INIT WARNING] $error');
    debugPrintStack(stackTrace: stackTrace);
  }

  ConnectivityService().start();
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final AuthService _authService = AuthService();

  @override
  void initState() {
    super.initState();
    _authService.addListener(_handleAuthStateChanged);
    // Force-stop the session whenever the device loses connectivity.
    ConnectivityService().addOfflineListener(_handleConnectionLost);
  }

  @override
  void dispose() {
    _authService.removeListener(_handleAuthStateChanged);
    ConnectivityService().removeOfflineListener(_handleConnectionLost);
    super.dispose();
  }

  /// Fired once per online → offline transition. If the user has an active
  /// session, end it immediately (no server round-trip — we're offline) and
  /// send them to the login screen where biometric unlock is still available.
  void _handleConnectionLost() {
    if (!mounted) return;
    if (!_authService.isAuthenticated) return;

    debugPrint('main: connection lost — force-stopping active session');
    _authService.forceStopSession(); // auth listener navigates to LoginPage

    // Give the navigation a frame to settle, then notify the user.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final context = AuthService.navigatorKey.currentContext;
      if (context == null || !context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text(
            'Connection lost — you were signed out. You can sign back in '
            'using your biometrics.',
          ),
          backgroundColor: Colors.redAccent,
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 5),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      );
    });
  }

  void _handleAuthStateChanged() {
    if (!mounted) return;

    final navigator = AuthService.navigatorKey.currentState;
    if (navigator == null) return;

    if (_authService.isAuthenticated) {
      navigator.pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => const MainLayout(showWelcomeGreeting: true),
        ),
        (route) => false,
      );
    } else {
      navigator.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginPage()),
        (route) => false,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: themeModeNotifier,
      builder: (context, currentMode, _) {
        return MaterialApp(
          scrollBehavior: AppScrollBehavior(),
          navigatorKey: AuthService.navigatorKey,
          debugShowCheckedModeBanner: false,
          title: 'REVELA',
          theme: AppTheme.theme,
          darkTheme: AppTheme.darkTheme,
          themeMode: currentMode,
          home: const SplashScreen(),
          builder: (context, child) {
            // Clamp the text scaling to prevent UI disarray on devices with large font sizes
            final mediaQueryData = MediaQuery.of(context);
            final scale = mediaQueryData.textScaler.clamp(
              minScaleFactor: 1.0,
              maxScaleFactor: 1.15,
            );
            return MediaQuery(
              data: mediaQueryData.copyWith(textScaler: scale),
              child: child!,
            );
          },
        );
      },
    );
  }
}

class AppScrollBehavior extends MaterialScrollBehavior {
  @override
  Set<PointerDeviceKind> get dragDevices => {
    PointerDeviceKind.touch,
    PointerDeviceKind.mouse,
    PointerDeviceKind.stylus,
    PointerDeviceKind.trackpad,
  };
}
