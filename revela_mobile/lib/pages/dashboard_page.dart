import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../component/inspection_modal.dart';
import '../service/inspection_service.dart';
import '../theme/app_theme.dart';
import '../widgets/task_card.dart';
import '../widgets/custom_app_bar.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../service/api_config.dart';
import '../service/auth_service.dart';
import 'package:table_calendar/table_calendar.dart';
import 'package:showcaseview/showcaseview.dart';
import 'inspection_page.dart';
import 'profile_page.dart';
import 'main_layout.dart';
import '../utils/date_utils.dart';

class DashboardPage extends StatefulWidget {
  final ValueChanged<bool>? onDrawerToggled;
  final ValueChanged<int>? onSwitchTab;
  const DashboardPage({super.key, this.onDrawerToggled, this.onSwitchTab});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage>
    with WidgetsBindingObserver {
  Timer? _pollTimer;
  final PageController _pageController = PageController(viewportFraction: 1.0);
  final ScrollController _dashboardScrollController = ScrollController();
  final GlobalKey _cardsTourTargetKey = GlobalKey();
  final GlobalKey _progressTourTargetKey = GlobalKey();
  final GlobalKey _flagsTourTargetKey = GlobalKey();
  final GlobalKey _calendarTourTargetKey = GlobalKey();
  final GlobalKey _assignmentsTourTargetKey = GlobalKey();
  double _currentPage = 0.0;
  final InspectionService _inspectionService = InspectionService();
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  String _inspectorName = 'Inspector';
  String _inspectorRole = 'BPLO Field Inspector';
  bool _isLoading = true;
  List<InspectionTask> _activeTasks = [];
  List<InspectionTask> _historyTasks = [];
  bool _isDrawerOpen = false;
  bool _isOffline = false;
  String? _lastSync;

  DateTime _focusedDay = DateTime.now();
  DateTime? _selectedDay = DateTime.now();
  CalendarFormat _calendarFormat = CalendarFormat.month;

  List<InspectionTask> _getTasksForDay(DateTime day) {
    return _activeTasks.where((task) {
      if (task.deadline == null) return false;
      final deadline = AppDateUtils.parseToLocal(task.deadline!);
      if (deadline == null) return false;
      return isSameDay(deadline, day);
    }).toList();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // ShowcaseView owns the overlay; the dashboard owns scrolling its content
    // into view before the overlay settles on each target.
    ShowcaseView.get().addOnStartCallback(_scrollTourTargetIntoView);
    _pageController.addListener(() {
      if (!mounted) return;
      if (_pageController.hasClients &&
          _pageController.positions.length == 1 &&
          _pageController.position.haveDimensions) {
        setState(() {
          _currentPage = _pageController.page!;
        });
      }
    });
    _loadCachedDashboardData();
    _loadDashboardData();
    _pollTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) {
        _loadDashboardData(silent: true);
      }
    });
  }

  Future<void> _loadCachedDashboardData() async {
    try {
      final auth = AuthService();
      String? userId = await auth.getAuthenticatedUserId();
      userId ??=
          await _storage.read(key: 'authenticated_user_id') ??
          await _storage.read(key: 'last_logged_in_user_id');
      final fullName =
          await _storage.read(key: 'user_fullName') ?? 'Field Inspector';
      final role =
          await _storage.read(key: 'user_role') ?? 'BPLO Field Inspector';

      if (userId == null || userId.isEmpty) {
        if (mounted) {
          setState(() {
            _inspectorName = fullName;
            _inspectorRole = role;
          });
        }
        return;
      }

      final localActive = await _inspectionService.getLocalTasksForUser(
        userId,
        activeOnly: true,
      );
      final localHistory = await _inspectionService.getLocalTasksForUser(
        userId,
        activeOnly: false,
      );
      if (mounted) {
        setState(() {
          _inspectorName = fullName;
          _inspectorRole = role;
          _activeTasks = localActive;
          _historyTasks = localHistory;
        });
      }
    } catch (e) {
      debugPrint('Dashboard local load failed: $e');
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _pageController.dispose();
    _dashboardScrollController.dispose();
    ShowcaseView.get().removeOnStartCallback(_scrollTourTargetIntoView);
    super.dispose();
  }

  void _scrollTourTargetIntoView(int? _, GlobalKey showcaseKey) {
    GlobalKey? targetKey;
    if (showcaseKey == MainLayout.dashboardCardsTourKey) {
      targetKey = _cardsTourTargetKey;
    } else if (showcaseKey == MainLayout.dashboardProgressTourKey) {
      targetKey = _progressTourTargetKey;
    } else if (showcaseKey == MainLayout.dashboardFlagsTourKey) {
      targetKey = _flagsTourTargetKey;
    } else if (showcaseKey == MainLayout.dashboardCalendarTourKey) {
      targetKey = _calendarTourTargetKey;
    } else if (showcaseKey == MainLayout.dashboardAssignmentsTourKey) {
      targetKey = _assignmentsTourTargetKey;
    }

    final targetContext = targetKey?.currentContext;
    if (targetContext == null || !_dashboardScrollController.hasClients) return;

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || targetKey?.currentContext == null) return;
      await Scrollable.ensureVisible(
        targetKey!.currentContext!,
        alignment: 0.12,
        duration: const Duration(milliseconds: 450),
        curve: Curves.easeInOutCubic,
      );
      if (mounted) ShowcaseView.get().updateOverlay();
    });
  }

  Widget _dashboardTourStep({
    required GlobalKey showcaseKey,
    required GlobalKey targetKey,
    required String title,
    required String description,
    required Widget child,
    EdgeInsets targetPadding = const EdgeInsets.all(4),
  }) {
    return Showcase(
      key: showcaseKey,
      title: title,
      description: description,
      targetPadding: targetPadding,
      // The barrier stays interactive, so a tap anywhere outside the focused
      // component advances the tour. The Next button is a clear alternative.
      disableBarrierInteraction: false,
      scaleAnimationDuration: const Duration(milliseconds: 260),
      movingAnimationDuration: const Duration(milliseconds: 320),
      tooltipActions: const [
        TooltipActionButton(
          type: TooltipDefaultActionType.next,
          name: 'Next',
        ),
      ],
      child: KeyedSubtree(key: targetKey, child: child),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _loadDashboardData(silent: true);
    }
  }

  void _openTask(InspectionTask task) async {
    if (!mounted) return;
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) =>
          InspectionModal(task: task, onSubmitted: _loadDashboardData),
    );

    if (!mounted) return;
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  String _getGreeting() {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning,';
    if (hour < 17) return 'Good afternoon,';
    return 'Good evening,';
  }

  Future<void> _loadDashboardData({bool silent = false}) async {
    if (!silent && mounted) {
      setState(() => _isLoading = true);
    }
    try {
      final name =
          await _storage.read(key: 'user_fullName') ?? 'Field Inspector';
      final role =
          await _storage.read(key: 'user_role') ?? 'BPLO Field Inspector';

      // Before probing backend reachability, attempt to load any locally cached
      // tasks so the UI can show existing assignments immediately while the
      // app retries background sync.
      try {
        final auth = AuthService();
        String? userId = await auth.getAuthenticatedUserId();
        if (userId == null || userId.isEmpty) {
          userId =
              await _storage.read(key: 'authenticated_user_id') ??
              await _storage.read(key: 'last_logged_in_user_id');
        }

        Map<String, dynamic>? cachedProfile;
        if (userId != null && userId.isNotEmpty) {
          cachedProfile = await auth.getCachedUserProfile(userId);
        }

        final displayName =
            cachedProfile?['fullName']?.toString().isNotEmpty == true
            ? cachedProfile!['fullName']!.toString()
            : name;
        final displayRole =
            cachedProfile?['role']?.toString().isNotEmpty == true
            ? cachedProfile!['role']!.toString()
            : role;

        if (userId != null && userId.isNotEmpty) {
          final localActive = await _inspectionService.getLocalTasksForUser(
            userId,
            activeOnly: true,
          );
          final localHistory = await _inspectionService.getLocalTasksForUser(
            userId,
            activeOnly: false,
          );
          if (mounted) {
            setState(() {
              _inspectorName = displayName;
              _inspectorRole = displayRole;
              _activeTasks = localActive;
              _historyTasks = localHistory;
              // Keep loading state until network probe completes unless silent
              if (silent) {
                _isLoading = false;
              }
            });
          }
        } else if (mounted) {
          setState(() {
            _inspectorName = displayName;
            _inspectorRole = displayRole;
            if (silent) {
              _isLoading = false;
            }
          });
        }
      } catch (localErr) {
        debugPrint('Failed to pre-load local tasks: $localErr');
      }

      // Check connectivity; if unreachable, InspectionService will fallback to local DB
      final reachable = await ApiConfig.ensureReachable();
      final wasOffline = _isOffline;
      _isOffline = reachable == null;

      final active = await _inspectionService.getMyTasks();
      final history = await _inspectionService.getMyReportHistory();

      // When online, record last sync timestamp so offline badge can show it later
      if (!_isOffline) {
        final now = DateTime.now().toIso8601String();
        await _storage.write(key: 'last_sync', value: now);
        _lastSync = now;
      } else {
        _lastSync = await _storage.read(key: 'last_sync');
      }

      if (mounted) {
        setState(() {
          _inspectorName = name;
          _inspectorRole = role;
          // If server returned nothing but we have previously-loaded local tasks,
          // prefer keeping them to avoid showing zero assignments.
          if (active.isEmpty && _activeTasks.isNotEmpty) {
            debugPrint(
              'Dashboard: keeping previously loaded local active tasks',
            );
            _activeTasks = _activeTasks;
          } else {
            _activeTasks = active;
          }

          if (history.isEmpty && _historyTasks.isNotEmpty) {
            debugPrint(
              'Dashboard: keeping previously loaded local history tasks',
            );
            _historyTasks = _historyTasks;
          } else {
            _historyTasks = history;
          }

          _isLoading = false;
        });
      }

      // If we were offline and are now online, attempt a background sync of pending reports
      if (wasOffline && !_isOffline) {
        // Fire-and-forget background sync; keep UI using already-loaded cached data
        Future.microtask(() => _inspectionService.syncPendingReports());
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final int assignedCount = _activeTasks.length;
    final int redFlagsCount = _activeTasks
        .where((t) => t.flagColor.toLowerCase() == 'red')
        .length;
    final int yellowFlagsCount = _activeTasks
        .where((t) => t.flagColor.toLowerCase() == 'yellow')
        .length;
    final int orangeFlagsCount = _activeTasks
        .where((t) => t.flagColor.toLowerCase() == 'orange')
        .length;
    final int submittedCount = _historyTasks
        .where((t) => t.verificationStatus.toLowerCase() == 'submitted')
        .length;
    final int verifiedCount = _historyTasks
        .where((t) => t.verificationStatus.toLowerCase() == 'verified')
        .length;

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: CustomAppBar(
        title: 'Dashboard',
        icon: Icons.dashboard_rounded,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: IconButton(
              icon: Icon(
                Icons.refresh_rounded,
                color: context.adaptiveTextMid,
                size: 26,
              ),
              onPressed: _isLoading ? null : _loadDashboardData,
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          SafeArea(
            child: Column(
              children: [
                // Offline status badge
                if (_isOffline)
                  Container(
                    width: double.infinity,
                    color: Colors.orange.shade100,
                    padding: const EdgeInsets.symmetric(
                      vertical: 8,
                      horizontal: 16,
                    ),
                    child: Text(
                      'Offline Mode — Logged in as $_inspectorName${_lastSync != null ? ' | Last sync: $_lastSync' : ''}',
                      style: TextStyle(color: Colors.orange.shade900),
                    ),
                  ),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: () async => _loadDashboardData(),
                    color: AppColors.gold,
                    backgroundColor: context.adaptiveSurface,
                    child: _isLoading
                        ? ListView.builder(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16.0,
                              vertical: 20.0,
                            ),
                            itemCount: 4,
                            itemBuilder: (context, index) => Padding(
                              padding: const EdgeInsets.only(bottom: 16.0),
                              child: Shimmer.fromColors(
                                baseColor: context.isDarkMode
                                    ? Colors.grey[800]!
                                    : Colors.grey[300]!,
                                highlightColor: context.isDarkMode
                                    ? Colors.grey[700]!
                                    : Colors.grey[100]!,
                                child: Container(
                                  height: index == 0 ? 100 : 160,
                                  decoration: BoxDecoration(
                                    color: Colors.white,
                                    borderRadius: BorderRadius.circular(24),
                                  ),
                                ),
                              ),
                            ),
                          )
                        : SingleChildScrollView(
                            controller: _dashboardScrollController,
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16.0,
                              vertical: 0.0,
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                // ── Modern Welcome Banner ──
                                _dashboardTourStep(
                                  showcaseKey: MainLayout.dashboardCardsTourKey,
                                  targetKey: _cardsTourTargetKey,
                                  title: 'Welcome Cards',
                                  description:
                                      'Here you can quickly see your most urgent tasks and overall progress.',
                                  targetPadding: const EdgeInsets.all(8),
                                  child: SizedBox(
                                    // Keep enough space for the card content,
                                    // while scaling with the available device height.
                                    height:
                                        (MediaQuery.sizeOf(context).height *
                                                0.35)
                                            .clamp(220.0, 320.0)
                                            .toDouble(),
                                    child: Stack(
                                      clipBehavior: Clip.none,
                                      children: [
                                        Container(
                                          margin: const EdgeInsets.only(
                                            top: 60,
                                            bottom: 20,
                                          ),
                                          width: double.infinity,
                                          child: PageView.builder(
                                            controller: _pageController,
                                            itemCount: 3,
                                            itemBuilder: (context, index) {
                                              return AnimatedBuilder(
                                                animation: _pageController,
                                                builder: (context, child) {
                                                  double page =
                                                      _pageController
                                                              .hasClients &&
                                                          _pageController
                                                                  .positions
                                                                  .length ==
                                                              1 &&
                                                          _pageController
                                                              .position
                                                              .haveDimensions
                                                      ? _pageController.page!
                                                      : _currentPage;
                                                  double value =
                                                      1 -
                                                      ((page - index).abs() *
                                                          0.15);
                                                  value = value.clamp(
                                                    0.85,
                                                    1.0,
                                                  );
                                                  double opacity =
                                                      1 -
                                                      ((page - index).abs() *
                                                          0.5);
                                                  opacity = opacity.clamp(
                                                    0.4,
                                                    1.0,
                                                  );
                                                  return Transform.scale(
                                                    scale: value,
                                                    child: Opacity(
                                                      opacity: opacity,
                                                      child: child,
                                                    ),
                                                  );
                                                },
                                                child: index == 0
                                                    ? GestureDetector(
                                                        onTap: () async {
                                                          if (!mounted) return;
                                                          final result =
                                                              await Navigator.push(
                                                                context,
                                                                MaterialPageRoute(
                                                                  builder: (_) =>
                                                                      const ProfilePage(),
                                                                ),
                                                              );
                                                          if (!mounted) return;
                                                          if (result == true) {
                                                            _loadDashboardData();
                                                          }
                                                        },
                                                        child: _buildBannerCard(
                                                          child: Padding(
                                                            padding:
                                                                const EdgeInsets.all(
                                                                  24.0,
                                                                ),
                                                            child: Row(
                                                              children: [
                                                                Container(
                                                                  decoration: BoxDecoration(
                                                                    shape: BoxShape
                                                                        .circle,
                                                                    border: Border.all(
                                                                      color: Colors
                                                                          .white,
                                                                      width: 2,
                                                                    ),
                                                                    boxShadow: [
                                                                      BoxShadow(
                                                                        color: AppColors
                                                                            .gold
                                                                            .withValues(
                                                                              alpha: 0.4,
                                                                            ),
                                                                        blurRadius:
                                                                            20,
                                                                        spreadRadius:
                                                                            8,
                                                                      ),
                                                                    ],
                                                                  ),
                                                                  child: CircleAvatar(
                                                                    radius: 32,
                                                                    backgroundColor:
                                                                        AppColors
                                                                            .gold,
                                                                    child: Text(
                                                                      _inspectorName
                                                                              .isNotEmpty
                                                                          ? _inspectorName[0].toUpperCase()
                                                                          : 'I',
                                                                      style: const TextStyle(
                                                                        fontSize:
                                                                            28,
                                                                        fontWeight:
                                                                            FontWeight.w500,
                                                                        color: Color(
                                                                          0xFF0F3E22,
                                                                        ),
                                                                      ),
                                                                    ),
                                                                  ),
                                                                ),
                                                                const SizedBox(
                                                                  width: 20,
                                                                ),
                                                                Expanded(
                                                                  child: Column(
                                                                    crossAxisAlignment:
                                                                        CrossAxisAlignment
                                                                            .start,
                                                                    mainAxisAlignment:
                                                                        MainAxisAlignment
                                                                            .center,
                                                                    children: [
                                                                      Text(
                                                                        _getGreeting(),
                                                                        style: TextStyle(
                                                                          color: Colors.white.withValues(
                                                                            alpha:
                                                                                0.7,
                                                                          ),
                                                                          fontSize:
                                                                              14,
                                                                          fontWeight:
                                                                              FontWeight.w500,
                                                                          letterSpacing:
                                                                              0.5,
                                                                        ),
                                                                      ),
                                                                      const SizedBox(
                                                                        height:
                                                                            4,
                                                                      ),
                                                                      Text(
                                                                        _inspectorName,
                                                                        style: const TextStyle(
                                                                          color:
                                                                              Colors.white,
                                                                          fontSize:
                                                                              24,
                                                                          fontWeight:
                                                                              FontWeight.bold,
                                                                        ),
                                                                        maxLines:
                                                                            1,
                                                                        overflow:
                                                                            TextOverflow.ellipsis,
                                                                      ),
                                                                      const SizedBox(
                                                                        height:
                                                                            12,
                                                                      ),
                                                                      Container(
                                                                        padding: const EdgeInsets.symmetric(
                                                                          horizontal:
                                                                              12,
                                                                          vertical:
                                                                              6,
                                                                        ),
                                                                        decoration: BoxDecoration(
                                                                          color: Colors.white.withValues(
                                                                            alpha:
                                                                                0.15,
                                                                          ),
                                                                          borderRadius: BorderRadius.circular(
                                                                            12,
                                                                          ),
                                                                          border: Border.all(
                                                                            color: Colors.white.withValues(
                                                                              alpha: 0.2,
                                                                            ),
                                                                          ),
                                                                        ),
                                                                        child: Row(
                                                                          mainAxisSize:
                                                                              MainAxisSize.min,
                                                                          children: [
                                                                            const Icon(
                                                                              Icons.verified,
                                                                              color: AppColors.gold,
                                                                              size: 16,
                                                                            ),
                                                                            const SizedBox(
                                                                              width: 6,
                                                                            ),
                                                                            Container(
                                                                              width: 4,
                                                                              height: 4,
                                                                              decoration: BoxDecoration(
                                                                                color: Colors.white.withValues(
                                                                                  alpha: 0.5,
                                                                                ),
                                                                                shape: BoxShape.circle,
                                                                              ),
                                                                            ),
                                                                            const SizedBox(
                                                                              width: 6,
                                                                            ),
                                                                            Text(
                                                                              _inspectorRole,
                                                                              style: const TextStyle(
                                                                                color: Colors.white,
                                                                                fontSize: 13,
                                                                                fontWeight: FontWeight.w600,
                                                                              ),
                                                                            ),
                                                                          ],
                                                                        ),
                                                                      ),
                                                                    ],
                                                                  ),
                                                                ),
                                                              ],
                                                            ),
                                                          ),
                                                        ),
                                                      )
                                                    : index == 1
                                                    ? _buildBannerCard(
                                                        child: Padding(
                                                          padding:
                                                              const EdgeInsets.all(
                                                                24.0,
                                                              ),
                                                          child: Column(
                                                            crossAxisAlignment:
                                                                CrossAxisAlignment
                                                                    .start,
                                                            mainAxisAlignment:
                                                                MainAxisAlignment
                                                                    .center,
                                                            children: [
                                                              Text(
                                                                "Today's Focus",
                                                                style: TextStyle(
                                                                  color: Colors
                                                                      .white
                                                                      .withValues(
                                                                        alpha:
                                                                            0.7,
                                                                      ),
                                                                  fontSize: 14,
                                                                  fontWeight:
                                                                      FontWeight
                                                                          .w500,
                                                                  letterSpacing:
                                                                      0.5,
                                                                ),
                                                              ),
                                                              const SizedBox(
                                                                height: 4,
                                                              ),
                                                              Text(
                                                                redFlagsCount >
                                                                        0
                                                                    ? 'Prioritize $redFlagsCount red flags'
                                                                    : 'You have $assignedCount pending tasks',
                                                                style: const TextStyle(
                                                                  color: Colors
                                                                      .white,
                                                                  fontSize: 22,
                                                                  fontWeight:
                                                                      FontWeight
                                                                          .bold,
                                                                ),
                                                                maxLines: 2,
                                                                overflow:
                                                                    TextOverflow
                                                                        .ellipsis,
                                                              ),
                                                              const SizedBox(
                                                                height: 12,
                                                              ),
                                                              Container(
                                                                padding:
                                                                    const EdgeInsets.symmetric(
                                                                      horizontal:
                                                                          12,
                                                                      vertical:
                                                                          6,
                                                                    ),
                                                                decoration: BoxDecoration(
                                                                  color: Colors
                                                                      .white
                                                                      .withValues(
                                                                        alpha:
                                                                            0.1,
                                                                      ),
                                                                  borderRadius:
                                                                      BorderRadius.circular(
                                                                        12,
                                                                      ),
                                                                ),
                                                                child: Row(
                                                                  mainAxisSize:
                                                                      MainAxisSize
                                                                          .min,
                                                                  children: [
                                                                    const Icon(
                                                                      Icons
                                                                          .bolt_rounded,
                                                                      color: AppColors
                                                                          .gold,
                                                                      size: 14,
                                                                    ),
                                                                    const SizedBox(
                                                                      width: 6,
                                                                    ),
                                                                    const Text(
                                                                      'Stay safe on the field',
                                                                      style: TextStyle(
                                                                        color: Colors
                                                                            .white,
                                                                        fontSize:
                                                                            12,
                                                                        fontWeight:
                                                                            FontWeight.w600,
                                                                      ),
                                                                    ),
                                                                  ],
                                                                ),
                                                              ),
                                                            ],
                                                          ),
                                                        ),
                                                      )
                                                    : _buildBannerCard(
                                                        child: Padding(
                                                          padding:
                                                              const EdgeInsets.all(
                                                                24.0,
                                                              ),
                                                          child: Column(
                                                            crossAxisAlignment:
                                                                CrossAxisAlignment
                                                                    .start,
                                                            mainAxisAlignment:
                                                                MainAxisAlignment
                                                                    .center,
                                                            children: [
                                                              Text(
                                                                'Quick Tip',
                                                                style: TextStyle(
                                                                  color: Colors
                                                                      .white
                                                                      .withValues(
                                                                        alpha:
                                                                            0.7,
                                                                      ),
                                                                  fontSize: 14,
                                                                  fontWeight:
                                                                      FontWeight
                                                                          .w500,
                                                                  letterSpacing:
                                                                      0.5,
                                                                ),
                                                              ),
                                                              const SizedBox(
                                                                height: 4,
                                                              ),
                                                              const Text(
                                                                'Ensure clear photos of all violations.',
                                                                style: TextStyle(
                                                                  color: Colors
                                                                      .white,
                                                                  fontSize: 22,
                                                                  fontWeight:
                                                                      FontWeight
                                                                          .bold,
                                                                ),
                                                                maxLines: 2,
                                                                overflow:
                                                                    TextOverflow
                                                                        .ellipsis,
                                                              ),
                                                              const SizedBox(
                                                                height: 12,
                                                              ),
                                                              Container(
                                                                padding:
                                                                    const EdgeInsets.symmetric(
                                                                      horizontal:
                                                                          12,
                                                                      vertical:
                                                                          6,
                                                                    ),
                                                                decoration: BoxDecoration(
                                                                  color: Colors
                                                                      .white
                                                                      .withValues(
                                                                        alpha:
                                                                            0.1,
                                                                      ),
                                                                  borderRadius:
                                                                      BorderRadius.circular(
                                                                        12,
                                                                      ),
                                                                ),
                                                                child: Row(
                                                                  mainAxisSize:
                                                                      MainAxisSize
                                                                          .min,
                                                                  children: [
                                                                    const Icon(
                                                                      Icons
                                                                          .lightbulb_rounded,
                                                                      color: AppColors
                                                                          .gold,
                                                                      size: 14,
                                                                    ),
                                                                    const SizedBox(
                                                                      width: 6,
                                                                    ),
                                                                    const Text(
                                                                      'Documentation is key',
                                                                      style: TextStyle(
                                                                        color: Colors
                                                                            .white,
                                                                        fontSize:
                                                                            12,
                                                                        fontWeight:
                                                                            FontWeight.w600,
                                                                      ),
                                                                    ),
                                                                  ],
                                                                ),
                                                              ),
                                                            ],
                                                          ),
                                                        ),
                                                      ),
                                              );
                                            },
                                          ),
                                        ),
                                        // Page Indicators
                                        Positioned(
                                          bottom: 0,
                                          left: 0,
                                          right: 0,
                                          child: Row(
                                            mainAxisAlignment:
                                                MainAxisAlignment.center,
                                            children: List.generate(3, (index) {
                                              return AnimatedContainer(
                                                duration: const Duration(
                                                  milliseconds: 300,
                                                ),
                                                margin:
                                                    const EdgeInsets.symmetric(
                                                      horizontal: 4,
                                                    ),
                                                width:
                                                    _currentPage.round() ==
                                                        index
                                                    ? 24.0
                                                    : 8.0,
                                                height: 8.0,
                                                decoration: BoxDecoration(
                                                  color:
                                                      _currentPage.round() ==
                                                          index
                                                      ? AppColors.gold
                                                      : Colors.grey.withValues(
                                                          alpha: 0.4,
                                                        ),
                                                  borderRadius:
                                                      BorderRadius.circular(4),
                                                ),
                                              );
                                            }),
                                          ),
                                        ),
                                        // Mascot Peaking Above Banner — moves left → center → right across the 3 cards
                                        Positioned(
                                          top: -30,
                                          left: 24,
                                          right: 24,
                                          child: AnimatedBuilder(
                                            animation: _pageController,
                                            builder: (context, child) {
                                              double page = 0.0;
                                              if (_pageController.hasClients &&
                                                  _pageController
                                                          .positions
                                                          .length ==
                                                      1 &&
                                                  _pageController
                                                      .position
                                                      .haveDimensions) {
                                                page =
                                                    _pageController.page ??
                                                    _currentPage;
                                              } else {
                                                page = _currentPage;
                                              }
                                              // page 0 -> -1.0 (left), page 1 -> 0.0 (center), page 2 -> 1.0 (right)
                                              final double x =
                                                  (page - 1.0) * 0.85;
                                              return Align(
                                                alignment: Alignment(x, -1.0),
                                                child: child,
                                              );
                                            },
                                            // Fixed-width box so Align has a definite size to position against —
                                            // this is what stops the mascot from clipping oddly at the left/right extremes.
                                            child: SizedBox(
                                              width: 140,
                                              child: ClipRect(
                                                child: Align(
                                                  alignment:
                                                      Alignment.topCenter,
                                                  heightFactor: 0.5,
                                                  child: Image.asset(
                                                    'assets/images/standing.png',
                                                    height: 180,
                                                    fit: BoxFit.contain,
                                                  ),
                                                ),
                                              ),
                                            ),
                                          ),
                                        ),
                                      ],
                                    ).animate().fadeIn(duration: 500.ms).slideX(begin: -0.05),
                                  ),
                                ),
                                const SizedBox(height: 24),

                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  crossAxisAlignment: CrossAxisAlignment.end,
                                  children: [
                                    Text(
                                      'Overall Progress',
                                      style: TextStyle(
                                        fontSize: 18,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptiveTextDark,
                                      ),
                                    ),
                                    Builder(
                                      builder: (context) {
                                        final realTotal =
                                            assignedCount +
                                            submittedCount +
                                            verifiedCount;
                                        return Text(
                                          '$realTotal Total Assignments',
                                          style: TextStyle(
                                            fontSize: 12,
                                            fontWeight: FontWeight.bold,
                                            color: context.adaptiveTextMid,
                                          ),
                                        );
                                      },
                                    ),
                                  ],
                                ).animate().fadeIn(delay: 100.ms),
                                const SizedBox(height: 16),
                                _dashboardTourStep(
                                      showcaseKey: MainLayout.dashboardProgressTourKey,
                                      targetKey: _progressTourTargetKey,
                                      title: 'Overall Progress Bar',
                                      description:
                                          'Track your workload: Assigned (Grey), Submitted (Gold), and Verified (Green).',
                                      targetPadding: const EdgeInsets.all(4),
                                      child: Builder(
                                        builder: (context) {
                                          int total =
                                              assignedCount +
                                              submittedCount +
                                              verifiedCount;
                                          if (total == 0) {
                                            total =
                                                1; // prevent division by zero
                                          }
                                          return Column(
                                            children: [
                                              Container(
                                                height: 18,
                                                width: double.infinity,
                                                clipBehavior: Clip.antiAlias,
                                                decoration: BoxDecoration(
                                                  color: context.isDarkMode
                                                      ? Colors.grey[800]
                                                      : Colors.grey[200],
                                                  borderRadius:
                                                      BorderRadius.circular(9),
                                                ),
                                                child: Row(
                                                  children: [
                                                    if (verifiedCount > 0)
                                                      Expanded(
                                                        flex: verifiedCount,
                                                        child: Container(
                                                          color: AppColors
                                                              .darkGreen,
                                                        ),
                                                      ),
                                                    if (submittedCount > 0)
                                                      Expanded(
                                                        flex: submittedCount,
                                                        child: Container(
                                                          color: AppColors.gold,
                                                        ),
                                                      ),
                                                    if (assignedCount > 0)
                                                      Expanded(
                                                        flex: assignedCount,
                                                        child: Container(
                                                          color:
                                                              Colors.grey[400],
                                                        ),
                                                      ),
                                                  ],
                                                ),
                                              ),
                                              const SizedBox(height: 12),
                                              Row(
                                                mainAxisAlignment:
                                                    MainAxisAlignment
                                                        .spaceBetween,
                                                children: [
                                                  _buildProgressLegend(
                                                    'Verified',
                                                    verifiedCount,
                                                    AppColors.darkGreen,
                                                  ),
                                                  _buildProgressLegend(
                                                    'Submitted',
                                                    submittedCount,
                                                    AppColors.gold,
                                                  ),
                                                  _buildProgressLegend(
                                                    'Assigned',
                                                    assignedCount,
                                                    Colors.grey[400]!,
                                                  ),
                                                ],
                                              ),
                                            ],
                                          );
                                        },
                                      ),
                                    )
                                    .animate()
                                    .fadeIn(delay: 200.ms)
                                    .slideY(begin: 0.1),
                                const SizedBox(height: 32),

                                // ── Metrics Grid ──
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      'Flag Reports',
                                      style: TextStyle(
                                        fontSize: 18,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptiveTextDark,
                                      ),
                                    ),
                                  ],
                                ).animate().fadeIn(delay: 300.ms),
                                const SizedBox(height: 16),
                                _dashboardTourStep(
                                  showcaseKey: MainLayout.dashboardFlagsTourKey,
                                  targetKey: _flagsTourTargetKey,
                                  title: 'Flag Reports',
                                  description:
                                      'Quickly gauge risk levels. Red, yellow, and orange flags indicate active priorities.',
                                  targetPadding: const EdgeInsets.all(4),
                                  child: Row(
                                    children: [
                                      Expanded(
                                        child: redFlagsCount > 0
                                            ? _buildGlassMetricCard(
                                                    'Red',
                                                    '$redFlagsCount',
                                                    Icons.flag_rounded,
                                                    Colors.red,
                                                    isZero: false,
                                                  )
                                                  .animate()
                                                  .boxShadow(
                                                    begin: BoxShadow(
                                                      color: Colors.red
                                                          .withValues(
                                                            alpha: 0.2,
                                                          ),
                                                      blurRadius: 10,
                                                    ),
                                                    end: BoxShadow(
                                                      color: Colors.red
                                                          .withValues(
                                                            alpha: 0.2,
                                                          ),
                                                      blurRadius: 20,
                                                    ),
                                                  )
                                                  .fadeIn(delay: 350.ms)
                                                  .scale(
                                                    begin: const Offset(
                                                      0.95,
                                                      0.95,
                                                    ),
                                                  )
                                            : _buildGlassMetricCard(
                                                    'Red',
                                                    '0',
                                                    Icons.flag_rounded,
                                                    Colors.red,
                                                    isZero: true,
                                                  )
                                                  .animate()
                                                  .fadeIn(delay: 350.ms)
                                                  .scale(
                                                    begin: const Offset(
                                                      0.95,
                                                      0.95,
                                                    ),
                                                  ),
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child:
                                            _buildGlassMetricCard(
                                                  'Yellow',
                                                  '$yellowFlagsCount',
                                                  Icons.flag_rounded,
                                                  Colors.amber,
                                                  isZero: yellowFlagsCount == 0,
                                                )
                                                .animate()
                                                .fadeIn(delay: 400.ms)
                                                .scale(
                                                  begin: const Offset(
                                                    0.95,
                                                    0.95,
                                                  ),
                                                ),
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child:
                                            _buildGlassMetricCard(
                                                  'Orange',
                                                  '$orangeFlagsCount',
                                                  Icons.flag_rounded,
                                                  Colors.orange,
                                                  isZero: orangeFlagsCount == 0,
                                                )
                                                .animate()
                                                .fadeIn(delay: 450.ms)
                                                .scale(
                                                  begin: const Offset(
                                                    0.95,
                                                    0.95,
                                                  ),
                                                ),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(height: 32),

                                // ── Calendar ──
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      'Deadlines Calendar',
                                      style: TextStyle(
                                        fontSize: 18,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptiveTextDark,
                                      ),
                                    ),
                                  ],
                                ).animate().fadeIn(delay: 400.ms),
                                const SizedBox(height: 16),
                                _dashboardTourStep(
                                  showcaseKey: MainLayout.dashboardCalendarTourKey,
                                  targetKey: _calendarTourTargetKey,
                                  title: 'Deadlines Calendar',
                                  description:
                                      'Visually manage your schedule. Dates with a dot indicate upcoming task deadlines.',
                                  targetPadding: const EdgeInsets.all(4),
                                  child: Container(
                                    padding: const EdgeInsets.all(12),
                                    decoration: BoxDecoration(
                                      color: context.adaptiveSurface,
                                      borderRadius: BorderRadius.circular(24),
                                      border: Border.all(
                                        color: context.isDarkMode
                                            ? Colors.grey.shade800
                                            : Colors.grey.shade200,
                                      ),
                                    ),
                                    child: Column(
                                      children: [
                                        TableCalendar<InspectionTask>(
                                          firstDay: DateTime.utc(2020, 1, 1),
                                          lastDay: DateTime.utc(2030, 12, 31),
                                          focusedDay: _focusedDay,
                                          calendarFormat: _calendarFormat,
                                          onFormatChanged: (format) {
                                            if (!mounted) return;
                                            if (_calendarFormat != format) {
                                              setState(() {
                                                _calendarFormat = format;
                                              });
                                            }
                                          },
                                          selectedDayPredicate: (day) =>
                                              isSameDay(_selectedDay, day),
                                          onDaySelected:
                                              (selectedDay, focusedDay) {
                                                if (!mounted) return;
                                                if (!isSameDay(
                                                  _selectedDay,
                                                  selectedDay,
                                                )) {
                                                  setState(() {
                                                    _selectedDay = selectedDay;
                                                    _focusedDay = focusedDay;
                                                  });
                                                }
                                              },
                                          onPageChanged: (focusedDay) {
                                            _focusedDay = focusedDay;
                                          },
                                          eventLoader: _getTasksForDay,
                                          calendarBuilders:
                                              CalendarBuilders<InspectionTask>(
                                                selectedBuilder:
                                                    (context, day, focusedDay) {
                                                      bool hasLateEvent = false;
                                                      final tasks =
                                                          _getTasksForDay(day);
                                                      for (final task in tasks) {
                                                        if (task.deadline !=
                                                            null) {
                                                          final deadline =
                                                              AppDateUtils.parseToLocal(
                                                                task.deadline!,
                                                              );
                                                          if (deadline !=
                                                                  null &&
                                                              deadline.isBefore(
                                                                DateTime.now(),
                                                              )) {
                                                            hasLateEvent = true;
                                                            break;
                                                          }
                                                        }
                                                      }
                                                      return Container(
                                                        margin:
                                                            const EdgeInsets.all(
                                                              6.0,
                                                            ),
                                                        alignment:
                                                            Alignment.center,
                                                        decoration: BoxDecoration(
                                                          color: hasLateEvent
                                                              ? Colors.redAccent
                                                              : AppColors
                                                                    .darkGreen,
                                                          shape:
                                                              BoxShape.circle,
                                                        ),
                                                        child: Text(
                                                          '${day.day}',
                                                          style:
                                                              const TextStyle(
                                                                color: Colors
                                                                    .white,
                                                              ),
                                                        ),
                                                      );
                                                    },
                                                singleMarkerBuilder:
                                                    (context, day, task) {
                                                      bool isLate = false;
                                                      if (task.deadline !=
                                                          null) {
                                                        final deadline =
                                                            DateTime.tryParse(
                                                              task.deadline!,
                                                            );
                                                        if (deadline != null &&
                                                            deadline.isBefore(
                                                              DateTime.now(),
                                                            )) {
                                                          isLate = true;
                                                        }
                                                      }
                                                      return Container(
                                                        margin:
                                                            const EdgeInsets.symmetric(
                                                              horizontal: 1.5,
                                                            ),
                                                        width: 7.0,
                                                        height: 7.0,
                                                        decoration: BoxDecoration(
                                                          shape:
                                                              BoxShape.circle,
                                                          color: isLate
                                                              ? Colors.redAccent
                                                              : AppColors
                                                                    .darkGreen,
                                                        ),
                                                      );
                                                    },
                                              ),
                                          calendarStyle: CalendarStyle(
                                            todayDecoration: BoxDecoration(
                                              color: AppColors.gold,
                                              shape: BoxShape.circle,
                                            ),
                                            selectedDecoration:
                                                const BoxDecoration(
                                                  color: AppColors.darkGreen,
                                                  shape: BoxShape.circle,
                                                ),
                                            defaultTextStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                            weekendTextStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                            outsideTextStyle: TextStyle(
                                              color: context.adaptiveTextMid,
                                            ),
                                          ),
                                          headerStyle: HeaderStyle(
                                            formatButtonVisible: true,
                                            formatButtonTextStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                            formatButtonDecoration:
                                                BoxDecoration(
                                                  border: Border.all(
                                                    color:
                                                        context.adaptiveTextMid,
                                                  ),
                                                  borderRadius:
                                                      BorderRadius.circular(12),
                                                ),
                                            titleCentered: true,
                                            titleTextStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                            leftChevronIcon: Icon(
                                              Icons.chevron_left,
                                              color: context.adaptiveTextDark,
                                            ),
                                            rightChevronIcon: Icon(
                                              Icons.chevron_right,
                                              color: context.adaptiveTextDark,
                                            ),
                                          ),
                                          daysOfWeekStyle: DaysOfWeekStyle(
                                            weekdayStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                            weekendStyle: TextStyle(
                                              color: context.adaptiveTextDark,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(height: 12),
                                        if (_getTasksForDay(
                                          _selectedDay ?? DateTime.now(),
                                        ).isNotEmpty)
                                          ListView.builder(
                                            padding: EdgeInsets.zero,
                                            shrinkWrap: true,
                                            physics:
                                                const NeverScrollableScrollPhysics(),
                                            itemCount: _getTasksForDay(
                                              _selectedDay ?? DateTime.now(),
                                            ).length,
                                            itemBuilder: (context, index) {
                                              final tasksForDay =
                                                  _getTasksForDay(
                                                    _selectedDay ??
                                                        DateTime.now(),
                                                  );
                                              return TaskCard(
                                                task: tasksForDay[index],
                                                isCurrent: true,
                                                onTap: () => _openTask(
                                                  tasksForDay[index],
                                                ),
                                              );
                                            },
                                          ),
                                      ],
                                    ),
                                  ),
                                ).animate().fadeIn(delay: 450.ms),
                                const SizedBox(height: 32),

                                // ── Recent Active Tasks ──
                                _dashboardTourStep(
                                  showcaseKey: MainLayout.dashboardAssignmentsTourKey,
                                  targetKey: _assignmentsTourTargetKey,
                                  title: 'Recent Assignments',
                                  description:
                                      'View actionable tasks. Tap a task to open the Inspection Modal. Select a date on the calendar to filter this list.',
                                  targetPadding: const EdgeInsets.all(4),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.spaceBetween,
                                        children: [
                                          Text(
                                            'Recent Assignments',
                                            style: TextStyle(
                                              fontSize: 18,
                                              fontWeight: FontWeight.bold,
                                              color: context.adaptiveTextDark,
                                            ),
                                          ),
                                          InkWell(
                                            onTap: () {
                                              if (!mounted) return;
                                              if (widget.onSwitchTab != null) {
                                                widget.onSwitchTab!(2);
                                              } else {
                                                Navigator.push(
                                                  context,
                                                  MaterialPageRoute(
                                                    builder: (_) =>
                                                        const InspectionPage(),
                                                  ),
                                                );
                                              }
                                            },
                                            child: Container(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    horizontal: 12,
                                                    vertical: 6,
                                                  ),
                                              decoration: BoxDecoration(
                                                color: AppColors.gold
                                                    .withValues(alpha: 0.15),
                                                borderRadius:
                                                    BorderRadius.circular(20),
                                              ),
                                              child: const Text(
                                                'View All',
                                                style: TextStyle(
                                                  color: Color(0xFFC79200),
                                                  fontWeight: FontWeight.bold,
                                                  fontSize: 13,
                                                ),
                                              ),
                                            ),
                                          ),
                                        ],
                                      ).animate().fadeIn(delay: 500.ms),
                                      const SizedBox(height: 16),

                                      if (_activeTasks.isEmpty)
                                        Container(
                                          width: double.infinity,
                                          padding: const EdgeInsets.symmetric(
                                            vertical: 40,
                                          ),
                                          decoration: BoxDecoration(
                                            color: context.adaptiveSurface,
                                            borderRadius: BorderRadius.circular(
                                              24,
                                            ),
                                            border: Border.all(
                                              color: context.isDarkMode
                                                  ? Colors.grey.shade800
                                                  : Colors.grey.shade200,
                                            ),
                                          ),
                                          child: Column(
                                            children: [
                                              Icon(
                                                Icons
                                                    .check_circle_outline_rounded,
                                                size: 64,
                                                color: Colors.grey.withValues(
                                                  alpha: 0.5,
                                                ),
                                              ),
                                              const SizedBox(height: 16),
                                              Text(
                                                "You're all caught up!",
                                                style: TextStyle(
                                                  color:
                                                      context.adaptiveTextMid,
                                                  fontSize: 16,
                                                  fontWeight: FontWeight.w500,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ).animate().fadeIn(delay: 600.ms)
                                      else
                                        ListView.builder(
                                          itemCount: _activeTasks.length > 5
                                              ? 5
                                              : _activeTasks.length,
                                          shrinkWrap: true,
                                          physics:
                                              const NeverScrollableScrollPhysics(),
                                          itemBuilder: (ctx, index) {
                                            final task = _activeTasks[index];
                                            return TaskCard(
                                                  task: task,
                                                  isCurrent: true,
                                                  onTap: () => _openTask(task),
                                                )
                                                .animate()
                                                .fadeIn(
                                                  delay: Duration(
                                                    milliseconds:
                                                        600 + (index * 100),
                                                  ),
                                                )
                                                .slideX(begin: 0.05);
                                          },
                                        ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGlassMetricCard(
    String title,
    String value,
    IconData icon,
    Color color, {
    bool isZero = false,
  }) {
    final effectiveColor = isZero ? Colors.grey : color;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
      decoration: BoxDecoration(
        color: context.adaptiveSurface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: context.isDarkMode
              ? Colors.grey.shade800
              : Colors.grey.shade200,
        ),
        boxShadow: [
          BoxShadow(
            color: effectiveColor.withValues(alpha: isZero ? 0.05 : 0.1),
            blurRadius: 15,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: effectiveColor.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: effectiveColor, size: 20),
          ),
          const SizedBox(height: 12),
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w900,
              color: isZero ? Colors.grey[400] : context.adaptiveTextDark,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: context.adaptiveTextMid,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  Widget _buildBannerCard({required Widget child}) {
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF2A5934), Color(0xFF3B7243)],
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
        ),
        borderRadius: BorderRadius.circular(28),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF2A5934).withValues(alpha: 0.3),
            blurRadius: 15,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Stack(
        children: [
          // Grid overlay
          Positioned.fill(child: CustomPaint(painter: _GridPainter())),
          child,
        ],
      ),
    );
  }

  Widget _buildProgressLegend(String label, int value, Color color) {
    return Row(
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(
          '$value $label',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: context.adaptiveTextMid,
          ),
        ),
      ],
    );
  }
}

class _GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withValues(alpha: 0.05)
      ..strokeWidth = 1.0;

    const double spacing = 30.0;

    for (double i = 0; i < size.width; i += spacing) {
      canvas.drawLine(Offset(i, 0), Offset(i, size.height), paint);
    }

    for (double i = 0; i < size.height; i += spacing) {
      canvas.drawLine(Offset(0, i), Offset(size.width, i), paint);
    }

    final plusPaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.15)
      ..strokeWidth = 1.5;

    const double plusSize = 4.0;

    for (double x = 0; x < size.width; x += spacing) {
      for (double y = 0; y < size.height; y += spacing) {
        canvas.drawLine(
          Offset(x - plusSize / 2, y),
          Offset(x + plusSize / 2, y),
          plusPaint,
        );
        canvas.drawLine(
          Offset(x, y - plusSize / 2),
          Offset(x, y + plusSize / 2),
          plusPaint,
        );
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
