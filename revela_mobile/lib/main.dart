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
import 'service/api_config.dart';
import 'service/runtime_build_config.dart';
import 'widgets/genuine_activity_observer.dart';

final ValueNotifier<ThemeMode> themeModeNotifier = ValueNotifier<ThemeMode>(
  ThemeMode.system,
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await ApiConfig.initialize();

  // Firebase configuration can be absent in a local/dev build. Push is
  // optional, so never let its initialization prevent the Flutter UI from
  // reaching runApp().
  if (!RuntimeBuildConfig.isQa) {
    try {
      await Firebase.initializeApp();
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      await PushNotifications.initialize();
    } catch (error, stackTrace) {
      debugPrint('[FIREBASE INIT WARNING] $error');
      debugPrintStack(stackTrace: stackTrace);
    }
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
  late bool _lastRoutedAuthState;

  @override
  void initState() {
    super.initState();
    _lastRoutedAuthState = _authService.isAuthenticated;
    _authService.addListener(_handleAuthStateChanged);
  }

  @override
  void dispose() {
    _authService.removeListener(_handleAuthStateChanged);
    super.dispose();
  }

  void _handleAuthStateChanged() {
    if (!mounted) return;
    final isAuthenticated = _authService.isAuthenticated;
    if (_lastRoutedAuthState == isAuthenticated) return;

    final navigator = AuthService.navigatorKey.currentState;
    if (navigator == null) return;
    _lastRoutedAuthState = isAuthenticated;

    if (isAuthenticated) {
      navigator.pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => const MainLayout(showWelcomeGreeting: true),
        ),
        (route) => false,
      );
    } else {
      navigator.pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) =>
              LoginPage(accountRevokedNotice: _authService.isAccountRevoked),
        ),
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
              child: GenuineActivityObserver(
                authService: _authService,
                child: child!,
              ),
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
