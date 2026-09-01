import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../main.dart';
import '../service/api_config.dart';
import '../service/auth_service.dart';
import '../service/assignment_notifications.dart';
import 'welcome_page.dart';
import 'login_page.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});
  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    bool seenWelcome = false;

    // 1. Read SharedPreferences first
    try {
      final prefs = await SharedPreferences.getInstance();
      seenWelcome = prefs.getBool('seen_welcome') ?? false;
      final String themePref = prefs.getString('theme_preference') ?? 'system';

      if (themePref == 'dark') {
        themeModeNotifier.value = ThemeMode.dark;
      } else if (themePref == 'light') {
        themeModeNotifier.value = ThemeMode.light;
      } else {
        themeModeNotifier.value = ThemeMode.system;
      }
    } catch (e) {
      debugPrint("SharedPreferences error: $e");
    }

    // 2. Initialize API config (safe)
    try {
      await ApiConfig.initialize();
      AuthService().syncBaseUrl();
    } catch (e) {
      debugPrint("ApiConfig initialization error: $e");
    }

    // 3. Initialize notifications (safe)
    try {
      await AssignmentNotifications.init();
    } catch (e) {
      debugPrint("AssignmentNotifications error: $e");
    }

    // Minimum display time for splash to look polished
    await Future.delayed(const Duration(milliseconds: 1500));

    if (!mounted) return;

    // 4. Navigate based on app state
    final Widget nextRoute =
        seenWelcome ? const LoginPage() : const WelcomePage();

    Navigator.pushReplacement(
      context,
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 600),
        pageBuilder: (context, animation, secondaryAnimation) => nextRoute,
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF1B5E20), // Dark green background
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 32,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      // Logo Container
                      Container(
                        width: 110,
                        height: 110,
                        decoration: BoxDecoration(
                          color: const Color(
                            0xFF388E3C,
                          ).withValues(alpha: 0.5), // Lighter green glow
                          borderRadius: BorderRadius.circular(28),
                        ),
                        child: Center(
                          child: Image.asset(
                            'assets/images/logo.png',
                            height: 65,
                          ),
                        ),
                      ).animate().scale(
                        delay: 200.ms,
                        duration: 600.ms,
                        curve: Curves.easeOutBack,
                      ),

                      const SizedBox(height: 24),

                      // App Name
                      const Text(
                        'REVELA',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 32,
                          fontWeight: FontWeight.w900,
                          color: Colors.white,
                          letterSpacing: 4,
                        ),
                      ).animate().fadeIn(delay: 500.ms).slideY(begin: 0.2),

                      const SizedBox(height: 8),

                      // Subtitle
                      Text(
                        'Field Inspection Platform',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 14,
                          color: Colors.white.withValues(alpha: 0.8),
                          letterSpacing: 1.5,
                        ),
                      ).animate().fadeIn(delay: 700.ms),

                      const SizedBox(height: 56),

                      // The spinner shares the same horizontal center as the
                      // logo and labels on every screen width.
                      const CircularProgressIndicator(
                        color: Colors.white,
                        strokeWidth: 3,
                      ).animate().fadeIn(delay: 1000.ms),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
