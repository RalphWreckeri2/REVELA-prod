import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'dashboard_page.dart';
import 'home_page.dart';
import 'inspection_page.dart';
import 'notifications_page.dart';
import 'settings_screen.dart';
import '../theme/app_theme.dart';
import '../widgets/app_background.dart';
import '../service/in_app_notifications_service.dart';
import '../service/push_notifications.dart';
import '../widgets/scale_tap.dart';
import '../widgets/floating_mascot.dart';
import 'dart:async';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:showcaseview/showcaseview.dart';

class MainLayout extends StatefulWidget {
  final int initialIndex;
  final bool showWelcomeGreeting;
  const MainLayout({
    super.key,
    this.initialIndex = 0,
    this.showWelcomeGreeting = false,
  });

  static final GlobalKey dashboardCardsTourKey = GlobalKey();
  static final GlobalKey dashboardProgressTourKey = GlobalKey();
  static final GlobalKey dashboardFlagsTourKey = GlobalKey();
  static final GlobalKey dashboardCalendarTourKey = GlobalKey();
  static final GlobalKey dashboardAssignmentsTourKey = GlobalKey();
  static final GlobalKey mapControlsTourKey = GlobalKey();
  static final GlobalKey mapLegendsTourKey = GlobalKey();
  static final GlobalKey mapAssignmentsBtnTourKey = GlobalKey();
  static final GlobalKey mapAddFlagBtnTourKey = GlobalKey();
  static final GlobalKey tasksSearchTourKey = GlobalKey();
  static final GlobalKey tasksFilterTourKey = GlobalKey();
  static final GlobalKey tasksTabsTourKey = GlobalKey();
  static final GlobalKey tasksPdfTourKey = GlobalKey();
  static final GlobalKey notificationsTourKey = GlobalKey();
  static final GlobalKey settingsAccountTourKey = GlobalKey();
  static final GlobalKey settingsPreferencesTourKey = GlobalKey();
  static final GlobalKey settingsOtherTourKey = GlobalKey();

  @override
  State<MainLayout> createState() => _MainLayoutState();
}

/// The visual contents are intentionally separate from the dismissal timer.
/// This keeps the welcome UI unchanged while MainLayout owns its lifecycle.
class _WelcomeLoadingOverlay extends StatelessWidget {
  const _WelcomeLoadingOverlay();

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: context.adaptiveSurface,
      child: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: SizedBox(
                  width: double.infinity,
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Spacer(flex: 3),
                      Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                                margin: const EdgeInsets.symmetric(
                                  horizontal: 32,
                                ),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 24,
                                  vertical: 24,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.white,
                                  borderRadius: BorderRadius.circular(28),
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(
                                        alpha: 0.08,
                                      ),
                                      blurRadius: 24,
                                      offset: const Offset(0, 12),
                                    ),
                                  ],
                                  border: Border.all(
                                    color: context.adaptivePrimary.withValues(
                                      alpha: 0.1,
                                    ),
                                    width: 1,
                                  ),
                                ),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(
                                      'Welcome Back!',
                                      style: TextStyle(
                                        fontSize: 24,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptivePrimary,
                                        letterSpacing: -0.5,
                                      ),
                                    ),
                                    const SizedBox(height: 12),
                                    const Text(
                                      'Just a moment while I prepare your workspace...',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                        fontSize: 15,
                                        color: Colors.black54,
                                        height: 1.4,
                                      ),
                                    ),
                                    const SizedBox(height: 24),
                                    Container(
                                      padding: const EdgeInsets.all(12),
                                      decoration: BoxDecoration(
                                        shape: BoxShape.circle,
                                        color: context.adaptivePrimary
                                            .withValues(alpha: 0.08),
                                      ),
                                      child: CircularProgressIndicator(
                                        color: context.adaptivePrimary,
                                        strokeWidth: 3,
                                      ),
                                    ),
                                  ],
                                ),
                              )
                              .animate()
                              .fadeIn(
                                delay: 200.ms,
                                duration: 600.ms,
                                curve: Curves.easeOutCubic,
                              )
                              .scale(
                                begin: const Offset(0.9, 0.9),
                                curve: Curves.easeOutCubic,
                              )
                              .slideY(begin: 0.1),
                          const SizedBox(height: 12),
                          Container(
                            width: 14,
                            height: 14,
                            decoration: BoxDecoration(
                              color: Colors.white,
                              shape: BoxShape.circle,
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.06),
                                  blurRadius: 8,
                                  offset: const Offset(0, 4),
                                ),
                              ],
                            ),
                          ).animate().fadeIn(delay: 500.ms).slideY(begin: 0.5),
                          const SizedBox(height: 8),
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: Colors.white,
                              shape: BoxShape.circle,
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.06),
                                  blurRadius: 8,
                                  offset: const Offset(0, 4),
                                ),
                              ],
                            ),
                          ).animate().fadeIn(delay: 650.ms).slideY(begin: 0.5),
                        ],
                      ),
                      const Spacer(flex: 1),
                      FloatingMascot(
                            imagePath: 'assets/images/waiting.png',
                            height: MediaQuery.sizeOf(context).height * 0.35,
                          )
                          .animate()
                          .fadeIn(duration: 800.ms, curve: Curves.easeOut)
                          .slideY(begin: 0.1, curve: Curves.easeOut),
                      const Spacer(flex: 2),
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

class _MainLayoutState extends State<MainLayout> {
  late int _selectedIndex;
  bool _isNavBarVisible = true;
  // Keep an already visited tab alive, but do not construct expensive tabs
  // (notably the Google Map/location tab) during the first Dashboard frame.
  // Constructing every IndexedStack child after login can block Android long
  // enough to trigger an ANR dialog on lower-end devices.
  late final List<Widget?> _pages;

  Timer? _pollingTimer;
  Timer? _welcomeDismissTimer;
  bool _isWelcomeGreetingVisible = false;

  double? _dragOffset;
  bool _isDragging = false;

  // True while the user is scrolling down through page content; makes the
  // navbar shrink. Goes back to false (navbar full size) when they scroll
  // back up.
  bool _isNavBarCollapsed = false;

  // True while the indicator should be popped out taller than the pill —
  // during a drag, and briefly after a tap/drag-end selection settles.
  // Goes back to false once it's settled on the chosen page, so the
  // indicator returns to its normal, flush-with-the-pill size.
  bool _isIndicatorPopped = false;
  Timer? _popTimer;

  @override
  void initState() {
    super.initState();
    // Guided instructions may target items below the fold.  Let the package
    // scroll the enclosing ListView/ScrollView before displaying each step.
    ShowcaseView.register(
      enableAutoScroll: true,
      scrollDuration: const Duration(milliseconds: 450),
    );
    _selectedIndex = widget.initialIndex.clamp(0, 4);
    _pages = List<Widget?>.filled(5, null);
    _ensurePageLoaded(_selectedIndex);
    _fetchUnreadCount();
    // Proactively refresh and sync FCM device token upon entering the workspace
    unawaited(PushNotifications.refreshFcmToken());
    _pollingTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _fetchUnreadCount();
    });

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _checkTabTour(_selectedIndex);
      if (widget.showWelcomeGreeting) _showWelcomeGreeting();
      if (PushNotifications.pendingReportId != null) {
        PushNotifications.pendingReportId = null;
        _onItemTapped(3);
      }
    });
  }

  Widget _createPage(int index) {
    switch (index) {
      case 0:
        return DashboardPage(
          onDrawerToggled: (expanded) {
            setState(() {
              _isNavBarVisible = !expanded;
            });
          },
          onSwitchTab: _onItemTapped,
        );
      case 1:
        return HomePage(
          onDrawerToggled: (expanded) {
            setState(() {
              _isNavBarVisible = !expanded;
            });
          },
        );
      case 2:
        return InspectionPage(
          onDrawerToggled: (expanded) {
            setState(() {
              _isNavBarVisible = !expanded;
            });
          },
        );
      case 3:
        return NotificationsPage(
          onDrawerToggled: (expanded) {
            setState(() {
              _isNavBarVisible = !expanded;
            });
          },
        );
      case 4:
        return const SettingsScreen();
      default:
        return const SizedBox.shrink();
    }
  }

  void _ensurePageLoaded(int index) {
    _pages[index] ??= _createPage(index);
  }

  void _showWelcomeGreeting() {
    if (!mounted) return;
    setState(() => _isWelcomeGreetingVisible = true);
    _welcomeDismissTimer?.cancel();
    _welcomeDismissTimer = Timer(const Duration(seconds: 2), () {
      if (!mounted) return;
      setState(() => _isWelcomeGreetingVisible = false);
    });
  }

  Future<void> _checkTabTour(int index) async {
    final prefs = await SharedPreferences.getInstance();

    String prefKey;
    List<GlobalKey> targetKeys;

    switch (index) {
      case 0:
        prefKey = 'has_seen_tour_dashboard';
        targetKeys = [
          MainLayout.dashboardCardsTourKey,
          MainLayout.dashboardProgressTourKey,
          MainLayout.dashboardFlagsTourKey,
          MainLayout.dashboardCalendarTourKey,
          MainLayout.dashboardAssignmentsTourKey,
        ];
        break;
      case 1:
        prefKey = 'has_seen_tour_map';
        targetKeys = [
          MainLayout.mapControlsTourKey,
          MainLayout.mapLegendsTourKey,
          MainLayout.mapAssignmentsBtnTourKey,
          MainLayout.mapAddFlagBtnTourKey,
        ];
        break;
      case 2:
        prefKey = 'has_seen_tour_tasks';
        targetKeys = [
          MainLayout.tasksSearchTourKey,
          MainLayout.tasksFilterTourKey,
          MainLayout.tasksTabsTourKey,
          MainLayout.tasksPdfTourKey,
        ];
        break;
      case 3:
        prefKey = 'has_seen_tour_notifications';
        targetKeys = [MainLayout.notificationsTourKey];
        break;
      case 4:
        prefKey = 'has_seen_tour_settings';
        targetKeys = [
          MainLayout.settingsAccountTourKey,
          MainLayout.settingsPreferencesTourKey,
          MainLayout.settingsOtherTourKey,
        ];
        break;
      default:
        return;
    }

    final hasSeenTour = prefs.getBool(prefKey) ?? false;
    if (!hasSeenTour) {
      // The dashboard tour can be read hands-free, while every manual tap
      // still completes the active step immediately. showcaseview cancels the
      // active timer during that transition and starts a fresh timer only for
      // the newly visible step, so a stale timer cannot skip an instruction.
      final showcase = ShowcaseView.get()
        ..autoPlay = index == 0
        ..autoPlayDelay = const Duration(seconds: 5)
        ..enableAutoPlayLock = false;

      void tryStartShowcase() {
        if (!mounted || _selectedIndex != index) return;
        if (targetKeys.isNotEmpty &&
            showcase.isTargetRendered(targetKeys.first)) {
          showcase.startShowCase(targetKeys);
          prefs.setBool(prefKey, true);
        } else {
          Future.delayed(const Duration(milliseconds: 500), tryStartShowcase);
        }
      }

      tryStartShowcase();
    }
  }

  Future<void> _fetchUnreadCount() async {
    try {
      await InAppNotificationsService().fetchUnreadCount();
    } catch (_) {}
  }

  @override
  void dispose() {
    _pollingTimer?.cancel();
    _popTimer?.cancel();
    _welcomeDismissTimer?.cancel();
    super.dispose();
  }

  void _onItemTapped(int index) {
    HapticFeedback.lightImpact();
    setState(() {
      _ensurePageLoaded(index);
      _selectedIndex = index;
    });
    _popIndicator();
    _checkTabTour(index);
  }

  // Pops the indicator taller than the pill right away, then — once it's
  // had time to land on the chosen tab — lets it animate back down to its
  // normal, flush size.
  void _popIndicator() {
    _popTimer?.cancel();
    setState(() => _isIndicatorPopped = true);
    _popTimer = Timer(const Duration(milliseconds: 300), () {
      if (mounted) setState(() => _isIndicatorPopped = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Scaffold paints its own opaque background by default; without this,
      // that base color shows through the navbar's transparent gaps.
      backgroundColor: Colors.transparent,
      extendBody: true, // Allows the body to flow underneath the bottom nav bar
      body: Stack(
        children: [
          AppBackground(
            child: NotificationListener<UserScrollNotification>(
              // ScrollNotifications bubble up past IndexedStack automatically,
              // so this catches scrolling from whichever page/tab is active
              // without each page needing to know about the navbar.
              onNotification: (notification) {
                if (notification.direction == ScrollDirection.reverse &&
                    !_isNavBarCollapsed) {
                  setState(() => _isNavBarCollapsed = true);
                } else if (notification.direction == ScrollDirection.forward &&
                    _isNavBarCollapsed) {
                  setState(() => _isNavBarCollapsed = false);
                }
                return false;
              },
              child: IndexedStack(
                index: _selectedIndex,
                children: [
                  for (final page in _pages) page ?? const SizedBox.shrink(),
                ],
              ),
            ),
          ),
          if (_isWelcomeGreetingVisible)
            const Positioned.fill(child: _WelcomeLoadingOverlay()),
        ],
      ),
      // Scaffold wraps bottomNavigationBar in its own opaque Material, which
      // can bleed elevation/shadow artifacts through our transparent gaps.
      // Giving it an explicit transparent Material of our own prevents that.
      bottomNavigationBar: _isWelcomeGreetingVisible
          ? null
          : Material(
              type: MaterialType.transparency,
              child: AnimatedSlide(
                duration: const Duration(milliseconds: 300),
                curve: Curves.easeInOut,
                offset: _isNavBarVisible ? Offset.zero : const Offset(0, 2.0),
                child: SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.only(
                      left: 20,
                      right: 20,
                      bottom: 24,
                      top: 8,
                    ),
                    child: AnimatedScale(
                      duration: const Duration(milliseconds: 200),
                      curve: Curves.easeInOut,
                      alignment: Alignment.bottomCenter,
                      scale: _isDragging
                          ? 0.96
                          : (_isNavBarCollapsed ? 0.82 : 1.0),
                      child: Stack(
                        // Clip.none lets the indicator layer below pop outside the
                        // pill's own footprint instead of being cut off at its edge.
                        clipBehavior: Clip.none,
                        children: [
                          // Layer 1: the frosted glass pill. This is the ONLY thing
                          // clipped to the rounded rect — the indicator lives
                          // outside this subtree so it's never subject to this clip.
                          Positioned.fill(
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(30),
                              child: BackdropFilter(
                                filter: ImageFilter.blur(
                                  sigmaX: 15,
                                  sigmaY: 15,
                                ),
                                child: Container(
                                  decoration: BoxDecoration(
                                    color: context.adaptiveSurface.withValues(
                                      alpha: 0.85,
                                    ),
                                    borderRadius: BorderRadius.circular(30),
                                    boxShadow: [
                                      BoxShadow(
                                        color: _isDragging
                                            ? AppColors.darkGreen.withValues(
                                                alpha: 0.3,
                                              )
                                            : Colors.black.withValues(
                                                alpha: 0.1,
                                              ),
                                        blurRadius: _isDragging ? 30 : 20,
                                        offset: const Offset(0, 10),
                                      ),
                                    ],
                                    border: Border.all(
                                      color: _isDragging
                                          ? AppColors.darkGreen.withValues(
                                              alpha: 0.5,
                                            )
                                          : (context.isDarkMode
                                                ? Colors.white24
                                                : Colors.black12),
                                      width: 1,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                          // Layer 2 & 3: indicator + icons. This subtree determines
                          // the Stack's size (matching the old content height) and
                          // is unclipped, so the indicator is free to render taller
                          // than the pill behind it.
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8.0,
                              vertical: 8.0,
                            ),
                            child: LayoutBuilder(
                              builder: (context, constraints) {
                                final tabWidth = constraints.maxWidth / 5;
                                final currentLeft =
                                    _isDragging && _dragOffset != null
                                    ? _dragOffset!
                                    : _selectedIndex * tabWidth;

                                final effectiveSelectedIndex =
                                    _isDragging && _dragOffset != null
                                    ? (_dragOffset! / tabWidth).round()
                                    : _selectedIndex;

                                return GestureDetector(
                                  onHorizontalDragStart: (details) {
                                    _popTimer?.cancel();
                                    setState(() {
                                      _isDragging = true;
                                      _isIndicatorPopped = true;
                                      _dragOffset = _selectedIndex * tabWidth;
                                    });
                                  },
                                  onHorizontalDragUpdate: (details) {
                                    setState(() {
                                      _dragOffset =
                                          (_dragOffset ?? 0) + details.delta.dx;
                                      if (_dragOffset! < 0) _dragOffset = 0;
                                      if (_dragOffset! >
                                          constraints.maxWidth - tabWidth) {
                                        _dragOffset =
                                            constraints.maxWidth - tabWidth;
                                      }
                                    });
                                  },
                                  onHorizontalDragEnd: (details) {
                                    final closestIndex =
                                        (_dragOffset! / tabWidth).round();
                                    setState(() {
                                      _isDragging = false;
                                      _dragOffset = null;
                                    });
                                    if (closestIndex != _selectedIndex) {
                                      // Changes the tab and, via _onItemTapped,
                                      // schedules the indicator's collapse.
                                      _onItemTapped(closestIndex);
                                    } else {
                                      // Same tab as before — still let the
                                      // indicator settle back to normal size.
                                      _popIndicator();
                                    }
                                  },
                                  child: Stack(
                                    // Not clipped to the icon row's own bounds, so
                                    // the AnimatedPositioned indicator below can
                                    // extend above/below it and still be visible.
                                    clipBehavior: Clip.none,
                                    children: [
                                      AnimatedPositioned(
                                        duration: Duration(
                                          milliseconds: _isDragging ? 0 : 350,
                                        ),
                                        curve: Curves.easeOutCirc,
                                        left: currentLeft,
                                        // Negative top/bottom pops the indicator
                                        // taller than the icon row while choosing a
                                        // tab; it animates back to 0 (flush with
                                        // the pill) once _isIndicatorPopped clears.
                                        top: _isIndicatorPopped ? -14 : 0,
                                        bottom: _isIndicatorPopped ? -14 : 0,
                                        width: tabWidth,
                                        child: Container(
                                          decoration: BoxDecoration(
                                            color: AppColors.darkGreen,
                                            borderRadius: BorderRadius.circular(
                                              26,
                                            ),
                                            boxShadow: [
                                              BoxShadow(
                                                color: AppColors.darkGreen
                                                    .withValues(alpha: 0.4),
                                                blurRadius: 16,
                                                offset: const Offset(0, 4),
                                              ),
                                            ],
                                          ),
                                        ),
                                      ),
                                      // Icons render after (on top of) the
                                      // indicator so they stay legible against it.
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.spaceAround,
                                        children: List.generate(5, (index) {
                                          IconData iconData;
                                          switch (index) {
                                            case 0:
                                              iconData =
                                                  Icons.dashboard_rounded;
                                              break;
                                            case 1:
                                              iconData = Icons.map_rounded;
                                              break;
                                            case 2:
                                              iconData =
                                                  Icons.assignment_rounded;
                                              break;
                                            case 3:
                                              iconData =
                                                  Icons.notifications_rounded;
                                              break;
                                            case 4:
                                              iconData = Icons.settings_rounded;
                                              break;
                                            default:
                                              iconData = Icons.circle;
                                          }

                                          final isSelected =
                                              effectiveSelectedIndex == index;
                                          return ScaleTap(
                                            scaleMinValue: 0.80,
                                            onTap: () => _onItemTapped(index),
                                            child: SizedBox(
                                              width: tabWidth,
                                              child: Padding(
                                                padding:
                                                    const EdgeInsets.symmetric(
                                                      vertical: 14,
                                                    ),
                                                child: Stack(
                                                  alignment: Alignment.center,
                                                  clipBehavior: Clip.none,
                                                  children: [
                                                    AnimatedScale(
                                                      scale: isSelected
                                                          ? 1.25
                                                          : 1.0,
                                                      duration: const Duration(
                                                        milliseconds: 300,
                                                      ),
                                                      curve: Curves.easeOutBack,
                                                      child: Icon(
                                                        iconData,
                                                        size: 24,
                                                        color: isSelected
                                                            ? Colors.white
                                                            : context
                                                                  .adaptiveTextMid,
                                                      ),
                                                    ),
                                                    if (index == 3)
                                                      ValueListenableBuilder<int>(
                                                        valueListenable:
                                                            InAppNotificationsService()
                                                                .unreadCountNotifier,
                                                        builder: (context, unread, _) {
                                                          if (unread <= 0) {
                                                            return const SizedBox.shrink();
                                                          }
                                                          return Positioned(
                                                            right:
                                                                (tabWidth / 2) - 20,
                                                            top: -4,
                                                            child: Container(
                                                              padding:
                                                                  const EdgeInsets.symmetric(
                                                                    horizontal: 5,
                                                                    vertical: 2,
                                                                  ),
                                                              decoration: BoxDecoration(
                                                                color: Colors
                                                                    .redAccent,
                                                                borderRadius:
                                                                    BorderRadius.circular(
                                                                      10,
                                                                    ),
                                                              ),
                                                              constraints:
                                                                  const BoxConstraints(
                                                                    minWidth: 18,
                                                                    minHeight: 18,
                                                                  ),
                                                              child: Text(
                                                                unread > 9
                                                                    ? '9+'
                                                                    : '$unread',
                                                                style:
                                                                    const TextStyle(
                                                                      color: Colors
                                                                          .white,
                                                                      fontSize: 10,
                                                                      fontWeight:
                                                                          FontWeight
                                                                              .bold,
                                                                      height: 1.4,
                                                                    ),
                                                                textAlign: TextAlign
                                                                    .center,
                                                              ),
                                                            ),
                                                          );
                                                        },
                                                      ),
                                                  ],
                                                ),
                                              ),
                                            ),
                                          );
                                        }),
                                      ),
                                    ],
                                  ),
                                );
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
    );
  }
}
