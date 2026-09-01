import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../theme/app_theme.dart';
import 'login_page.dart';
import 'package:permission_handler/permission_handler.dart';

class WelcomePage extends StatefulWidget {
  const WelcomePage({super.key});

  @override
  State<WelcomePage> createState() => _WelcomePageState();
}

class _WelcomePageState extends State<WelcomePage>
    with SingleTickerProviderStateMixin {
  late AnimationController _animController;
  late Animation<double> _fadeAnim;
  late Animation<Offset> _slideAnim;

  Future<void> _requestPermissions() async {
    try {
      await [
        Permission.camera,
        Permission.location,
        Permission.notification,
      ].request();
    } catch (e) {
      debugPrint('Permission request error: $e');
    }
  }

  final List<_WelcomeSlide> _slides = const [
    _WelcomeSlide(
      icon: Icons.search_rounded,
      title: 'Locate Unregistered\nBusinesses',
      description:
          'Use real-time maps to navigate to businesses that have not yet secured their permits.',
    ),
    _WelcomeSlide(
      icon: Icons.camera_alt_rounded,
      title: 'Document &\nCapture Evidence',
      description:
          'Take photos and record inspection findings directly in the field.',
    ),
    _WelcomeSlide(
      icon: Icons.cloud_upload_rounded,
      title: 'Submit Reports\nInstantly',
      description:
          'File inspection reports on the spot, synced to the BPLO portal in real time.',
    ),
  ];

  int _currentIndex = 0;
  final PageController _pageController = PageController();

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _fadeAnim = CurvedAnimation(parent: _animController, curve: Curves.easeIn);
    _slideAnim = Tween<Offset>(
      begin: const Offset(0, 0.12),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _animController, curve: Curves.easeOut));
    _animController.forward();
  }

  @override
  void dispose() {
    _animController.dispose();
    _pageController.dispose();
    super.dispose();
  }

  void _skip() async {
    await _requestPermissions();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('seen_welcome', true);
    if (mounted) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const LoginPage()),
      );
    }
  }

  void _next() async {
    if (_currentIndex < _slides.length - 1) {
      _pageController.nextPage(
        duration: const Duration(milliseconds: 400),
        curve: Curves.easeInOut,
      );
    } else {
      _skip();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.adaptiveBackground,
      body: SafeArea(
        child: FadeTransition(
          opacity: _fadeAnim,
          child: SlideTransition(
            position: _slideAnim,
            child: Column(
              children: [
                // Skip button
                Align(
                  alignment: Alignment.topRight,
                  child: Padding(
                    padding: const EdgeInsets.only(top: 12, right: 24),
                    child: TextButton(
                      onPressed: _skip,
                      child: Text(
                        'Skip',
                        style: TextStyle(
                          color: context.adaptiveTextLight,
                          fontSize: 14,
                        ),
                      ),
                    ),
                  ),
                ),

                // Logo area
                Container(
                  margin: const EdgeInsets.only(top: 8, bottom: 32),
                  child: Column(
                    children: [
                      Image.asset('assets/images/logo.png', height: 80),
                      SizedBox(height: 12),
                      Text(
                        'REVELA',
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                          color: context.adaptivePrimary,
                          letterSpacing: 3,
                        ),
                      ),
                    ],
                  ),
                ),

                // Slides
                Expanded(
                  child: PageView.builder(
                    controller: _pageController,
                    onPageChanged: (i) => setState(() => _currentIndex = i),
                    itemCount: _slides.length,
                    itemBuilder: (context, index) {
                      return _SlideContent(slide: _slides[index]);
                    },
                  ),
                ),

                // Dots
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List.generate(_slides.length, (i) {
                    final active = i == _currentIndex;
                    return AnimatedContainer(
                      duration: const Duration(milliseconds: 300),
                      margin: const EdgeInsets.symmetric(horizontal: 4),
                      width: active ? 24 : 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: active
                            ? AppColors.darkGreen
                            : context.adaptiveBorder,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    );
                  }),
                ),
                SizedBox(height: 32),

                // CTA Button
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 28),
                  child: SizedBox(
                    width: double.infinity,
                    height: 54,
                    child: ElevatedButton(
                      onPressed: _next,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.darkGreen,
                        foregroundColor: AppColors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                      ),
                      child: Text(
                        _currentIndex < _slides.length - 1
                            ? 'Next'
                            : 'Get Started',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ),
                  ),
                ),
                SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SlideContent extends StatelessWidget {
  final _WelcomeSlide slide;
  const _SlideContent({required this.slide});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 36),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Icon card
          Container(
                width: 160,
                height: 160,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [Color(0xFF2E7D32), Color(0xFF1B5E20)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(40),
                ),
                child: Icon(slide.icon, size: 72, color: AppColors.gold),
              )
              .animate()
              .fadeIn(duration: 500.ms)
              .scale(delay: 100.ms)
              .shimmer(delay: 800.ms, duration: 1000.ms),
          SizedBox(height: 40),
          Text(
            slide.title,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w800,
              color: context.adaptiveTextDark,
              height: 1.25,
            ),
          ).animate().fadeIn(delay: 300.ms).slideY(begin: 0.2, end: 0),
          SizedBox(height: 16),
          Text(
            slide.description,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 15,
              color: context.adaptiveTextMid,
              height: 1.6,
            ),
          ).animate().fadeIn(delay: 500.ms).slideY(begin: 0.2, end: 0),
        ],
      ),
    );
  }
}

class _WelcomeSlide {
  final IconData icon;
  final String title;
  final String description;
  const _WelcomeSlide({
    required this.icon,
    required this.title,
    required this.description,
  });
}
