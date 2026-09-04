import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import 'dart:async';
import '../component/inspection_modal.dart';
import '../service/in_app_notifications_service.dart';
import '../service/inspection_service.dart';
import '../theme/app_theme.dart';
import '../widgets/custom_app_bar.dart';
import '../widgets/floating_mascot.dart';
import 'package:showcaseview/showcaseview.dart';
import 'main_layout.dart';
import '../widgets/task_card.dart';
import '../widgets/modern_segmented_filter.dart';
import '../utils/date_utils.dart';

class NotificationsPage extends StatefulWidget {
  final ValueChanged<bool>? onDrawerToggled;
  final String? initialReportId;

  const NotificationsPage({
    super.key,
    this.onDrawerToggled,
    this.initialReportId,
  });

  @override
  State<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends State<NotificationsPage>
    with WidgetsBindingObserver {
  List<InAppNotification> _items = [];
  List<InspectionTask> _activeTasks = [];
  bool _loading = true;
  String? _error;
  bool _isOfflineMode = false;
  bool _isDrawerOpen = false;
  Timer? _pollingTimer;
  bool _loadInFlight = false;
  bool _autoOpenAttempted = false;
  int _currentFilterIndex = 0;
  late PageController _pageController;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pageController = PageController();
    _load();
    _startPolling();
  }

  void _startPolling() {
    _pollingTimer ??= Timer.periodic(const Duration(seconds: 25), (_) {
      _load(silent: true);
    });
  }

  void _stopPolling() {
    _pollingTimer?.cancel();
    _pollingTimer = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _startPolling();
      _load(silent: _items.isNotEmpty || _activeTasks.isNotEmpty);
    } else if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _stopPolling();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stopPolling();
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (_loadInFlight) return;
    _loadInFlight = true;
    final hasCachedContent = _items.isNotEmpty || _activeTasks.isNotEmpty;

    if (!silent && !hasCachedContent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final list = await InAppNotificationsService().fetchNotifications();
      final tasks = await InspectionService().getMyTasks();
      if (mounted) {
        setState(() {
          _items = list;
          _activeTasks = tasks;
          _loading = false;
          _isOfflineMode = false;
          _error = null;
        });

        // Automatically open task modal if arriving via notification deep link
        if (widget.initialReportId != null && !_autoOpenAttempted) {
          final targetId = int.tryParse(widget.initialReportId!);
          if (targetId != null) {
            InspectionTask? targetTask;
            for (final t in tasks) {
              if (t.reportID == targetId) {
                targetTask = t;
                break;
              }
            }
            if (targetTask != null) {
              _autoOpenAttempted = true;
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted) _onTaskTap(targetTask!);
              });
            }
          }
        }
      }
    } catch (e) {
      if (mounted) {
        try {
          final tasks = await InspectionService().getMyTasks();
          final cachedList =
              await InAppNotificationsService().loadCachedNotifications();
          setState(() {
            _items = cachedList;
            _activeTasks = tasks;
            _loading = false;
            _isOfflineMode = true;
            _error = (cachedList.isEmpty && tasks.isEmpty)
                ? 'No notifications available offline.'
                : null;
          });
        } catch (_) {
          setState(() {
            _error = hasCachedContent ? null : 'Could not load notifications.';
            _loading = false;
          });
        }
      }
    } finally {
      _loadInFlight = false;
    }
  }

  IconData _iconForType(String type) {
    switch (type) {
      case 'inspection_assigned':
        return Icons.assignment_ind_outlined;
      default:
        return Icons.notifications_outlined;
    }
  }

  void _onTaskTap(InspectionTask task) async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => InspectionModal(task: task, onSubmitted: () => _load()),
    );
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  @override
  Widget build(BuildContext context) {
    final nearingTasks = _activeTasks.where((task) {
      if (task.deadline == null || task.deadline!.isEmpty) return false;
      try {
        final deadline = AppDateUtils.parseToLocal(task.deadline!);
        if (deadline == null || deadline.isBefore(DateTime.now())) return false;
        final diff = deadline.difference(DateTime.now());
        return diff.inHours <= 24;
      } catch (_) {
        return false;
      }
    }).toList();

    final hasUnread = _items.any((n) => n.isUnread);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: CustomAppBar(
        title: 'Notifications',
        icon: Icons.notifications_active_rounded,
        actions: [
          if (_items.isNotEmpty) ...[
            IconButton(
              icon: const Icon(
                Icons.delete_sweep_outlined,
                color: Colors.redAccent,
                size: 24,
              ),
              tooltip: 'Clear all notifications',
              onPressed: _loading
                  ? null
                  : () async {
                      final confirm = await showDialog<bool>(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          title: const Text('Clear All'),
                          content: const Text(
                            'Are you sure you want to permanently delete all notifications?',
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, false),
                              child: const Text('Cancel'),
                            ),
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, true),
                              child: const Text(
                                'Clear',
                                style: TextStyle(color: Colors.redAccent),
                              ),
                            ),
                          ],
                        ),
                      );
                      if (confirm == true) {
                        setState(() => _loading = true);
                        await InAppNotificationsService()
                            .deleteAllNotifications();
                        await _load();
                      }
                    },
            ),
            if (hasUnread)
              IconButton(
                icon: Icon(
                  Icons.mark_email_read_outlined,
                  color: AppColors.darkGreen,
                  size: 22,
                ),
                tooltip: 'Mark all as read',
                onPressed: _loading
                    ? null
                    : () async {
                        await InAppNotificationsService().markAllRead();
                        _load(silent: true);
                      },
              ),
          ],
          Padding(
            padding: const EdgeInsets.only(right: 24.0, left: 8.0),
            child: Container(
              decoration: BoxDecoration(
                color: context.isDarkMode ? Colors.grey[800] : Colors.grey[100],
                borderRadius: BorderRadius.circular(16),
              ),
              child: IconButton(
                icon: Icon(
                  Icons.refresh_rounded,
                  color: context.adaptiveTextDark,
                  size: 24,
                ),
                onPressed: _loading ? null : _load,
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (widget.initialReportId != null)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.darkGreen.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'Inspection alert: report #${widget.initialReportId}',
                  style: TextStyle(
                    color: context.adaptiveTextDark,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),

            if (_isOfflineMode) _buildOfflineBanner(),

            // ── Filter Tabs ──
            Showcase(
              key: MainLayout.notificationsTourKey,
              title: 'Notifications',
              description: 'Important alerts and messages will appear here.',
              targetPadding: const EdgeInsets.all(4),
              child: ModernSegmentedFilter(
                options: [
                  hasUnread ? 'Assignments •' : 'Assignments',
                  nearingTasks.isNotEmpty ? 'Deadlines •' : 'Deadlines',
                ],
                selectedIndex: _currentFilterIndex,
                onSelected: (idx) {
                  _pageController.animateToPage(
                    idx,
                    duration: const Duration(milliseconds: 300),
                    curve: Curves.easeInOut,
                  );
                },
                padding: const EdgeInsets.symmetric(horizontal: 24),
              ),
            ),
            const SizedBox(height: 8),

            // ── Body ──
            Expanded(
              child: Stack(
                children: [
                  PageView(
                    controller: _pageController,
                    onPageChanged: (idx) =>
                        setState(() => _currentFilterIndex = idx),
                    children: [
                      _buildAssignmentsTab(),
                      _buildDeadlinesTab(nearingTasks),
                    ],
                  ),
                  if (_loading)
                    Positioned.fill(
                      child: Container(
                        color: context.adaptiveBackground,
                        child: _buildShimmer(context),
                      ),
                    ),
                  if (_error != null && !_loading)
                    Positioned.fill(
                      child: Container(
                        color: context.adaptiveBackground,
                        child: Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24.0),
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(
                                  Icons.error_outline_rounded,
                                  size: 48,
                                  color: Colors.red[300],
                                ),
                                const SizedBox(height: 16),
                                Text(
                                  _error!,
                                  style: TextStyle(
                                    color: Colors.red[300],
                                    fontSize: 16,
                                  ),
                                ),
                                const SizedBox(height: 24),
                                ElevatedButton.icon(
                                  onPressed: () => _load(),
                                  icon: const Icon(Icons.refresh_rounded),
                                  label: const Text('Retry'),
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: Colors.red[50],
                                    foregroundColor: Colors.red[700],
                                    elevation: 0,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
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

  Widget _buildOfflineBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 12),
      decoration: BoxDecoration(
        color: Colors.amber.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.amber.shade300),
      ),
      child: Row(
        children: [
          Icon(Icons.wifi_off_rounded, size: 18, color: Colors.amber.shade900),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'Offline Mode — Displaying cached notifications & assignments',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: Colors.amber.shade900,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildShimmer(BuildContext context) {
    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 12.0),
      itemCount: 5,
      itemBuilder: (context, index) => Padding(
        padding: const EdgeInsets.only(bottom: 12.0),
        child: Shimmer.fromColors(
          baseColor: context.isDarkMode ? Colors.grey[800]! : Colors.grey[300]!,
          highlightColor: context.isDarkMode
              ? Colors.grey[700]!
              : Colors.grey[100]!,
          child: Container(
            height: 88,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAssignmentsTab() {
    if (_items.isEmpty) {
      if (_activeTasks.isNotEmpty) {
        return ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 120),
          itemCount: _activeTasks.length,
          separatorBuilder: (_, _) => const SizedBox(height: 12),
          itemBuilder: (_, i) {
            final task = _activeTasks[i];
            return TaskCard(
              task: task,
              isCurrent: true,
              onTap: () => _onTaskTap(task),
            );
          },
        );
      }
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              FloatingMascot(
                imagePath: 'assets/images/searching.png',
                height: 160,
              ),
              const SizedBox(height: 16),
              Text(
                _isOfflineMode
                    ? 'No cached notifications available.'
                    : 'No notifications yet.',
                style: TextStyle(
                  color: AppColors.textLight,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                _isOfflineMode
                    ? 'Connect to the internet to fetch fresh notifications.'
                    : 'New assignments from admin will appear here.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textLight, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 120),
      itemCount: _items.length,
      separatorBuilder: (_, _) => const SizedBox(height: 10),
      itemBuilder: (_, i) {
        final n = _items[i];
        return Dismissible(
          key: ValueKey(n.id),
          direction: DismissDirection.endToStart,
          background: Container(
            alignment: Alignment.centerRight,
            padding: const EdgeInsets.only(right: 20),
            decoration: BoxDecoration(
              color: Colors.redAccent,
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.delete_outline, color: Colors.white),
          ),
          onDismissed: (direction) {
            setState(() {
              _items.removeWhere((item) => item.id == n.id);
            });
            InAppNotificationsService().deleteNotification(n.id);
          },
          child: GestureDetector(
            onTap: () async {
              if (n.isUnread) {
                try {
                  await InAppNotificationsService().markRead([n.id]);
                  if (mounted) {
                    setState(() {
                      _items[i] = InAppNotification(
                        id: n.id,
                        type: n.type,
                        title: n.title,
                        body: n.body,
                        createdAt: n.createdAt,
                        readAt: DateTime.now().toIso8601String(),
                      );
                    });
                  }
                } catch (_) {}
              }

              if (n.type == 'inspection_assigned') {
                final match = RegExp(r'\(report #(\d+)\)').firstMatch(n.body);
                final reportId = match != null
                    ? int.tryParse(match.group(1) ?? '')
                    : null;
                if (reportId != null) {
                  InspectionTask? task;
                  for (var t in _activeTasks) {
                    if (t.reportID == reportId) {
                      task = t;
                      break;
                    }
                  }
                  if (task != null) {
                    _onTaskTap(task);
                    return;
                  }
                }
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Task no longer active or found.'),
                    ),
                  );
                }
              }
            },
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: n.isUnread
                    ? AppColors.darkGreen.withValues(alpha: 0.06)
                    : context.adaptiveSurface,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: n.isUnread
                      ? AppColors.darkGreen.withValues(alpha: 0.25)
                      : context.isDarkMode
                      ? Colors.grey.shade800
                      : Colors.grey.shade200,
                ),
                boxShadow: [
                  if (n.isUnread)
                    BoxShadow(
                      color: AppColors.darkGreen.withValues(alpha: 0.05),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                ],
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: n.isUnread
                          ? AppColors.darkGreen.withValues(alpha: 0.1)
                          : context.isDarkMode
                          ? Colors.grey.shade800
                          : Colors.grey.shade100,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      _iconForType(n.type),
                      color: n.isUnread
                          ? AppColors.darkGreen
                          : context.adaptiveTextMid,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          n.title,
                          style: TextStyle(
                            fontWeight: n.isUnread
                                ? FontWeight.w700
                                : FontWeight.w600,
                            fontSize: 14,
                            color: context.adaptiveTextDark,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          n.body,
                          style: TextStyle(
                            fontSize: 13,
                            color: context.adaptiveTextMid,
                            height: 1.4,
                          ),
                        ),
                        if (n.createdAt.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text(
                            AppDateUtils.formatRelative(n.createdAt),
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w500,
                              color: context.adaptiveTextLight,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (n.isUnread)
                    Container(
                      width: 8,
                      height: 8,
                      margin: const EdgeInsets.only(top: 4),
                      decoration: const BoxDecoration(
                        color: AppColors.darkGreen,
                        shape: BoxShape.circle,
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildDeadlinesTab(List<InspectionTask> nearingTasks) {
    if (nearingTasks.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              FloatingMascot(
                imagePath: 'assets/images/standing.png',
                height: 160,
              ),
              const SizedBox(height: 16),
              Text(
                'All clear!',
                style: TextStyle(
                  color: AppColors.textLight,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'No approaching deadlines in the next 24 hours.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textLight, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 120),
      itemCount: nearingTasks.length,
      itemBuilder: (ctx, index) {
        return TaskCard(
          task: nearingTasks[index],
          isCurrent: true,
          onTap: () => _onTaskTap(nearingTasks[index]),
        );
      },
    );
  }
}
