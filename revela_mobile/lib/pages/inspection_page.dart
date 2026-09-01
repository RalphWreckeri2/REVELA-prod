import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import 'package:showcaseview/showcaseview.dart';
import 'main_layout.dart';
import '../component/inspection_modal.dart';
import '../widgets/floating_mascot.dart';
import '../service/inspection_service.dart';
import '../service/auth_service.dart';
import '../theme/app_theme.dart';
import '../widgets/task_card.dart';
import '../widgets/modern_segmented_filter.dart';
import '../widgets/custom_app_bar.dart';
import 'history_detail_page.dart';
import 'pdf_generator_page.dart';

class InspectionPage extends StatefulWidget {
  final ValueChanged<bool>? onDrawerToggled;
  const InspectionPage({super.key, this.onDrawerToggled});

  @override
  State<InspectionPage> createState() => _InspectionPageState();
}

class _InspectionPageState extends State<InspectionPage>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  static const Set<String> _activeStatuses = {'assigned', 'reassigned'};

  late TabController _tabController;
  int _currentFilterIndex = 0;

  List<InspectionTask> _currentTasks = [];
  List<InspectionTask> _missingTasks = [];
  List<InspectionTask> _historyTasks = [];
  String _selectedStatus = 'All';
  String _selectedResult = 'All';
  String _selectedBarangay = 'All';
  String _selectedSort = 'Newest';
  String _searchQuery = '';
  final TextEditingController _searchController = TextEditingController();
  bool _showFilters = false;
  bool _loadingCurrent = true;
  bool _loadingHistory = true;
  Timer? _refreshTimer;

  List<InspectionTask> get _activeTabTasks {
    if (_currentFilterIndex == 0) return _currentTasks;
    if (_currentFilterIndex == 1) return _missingTasks;
    return _historyTasks;
  }

  List<String> get _availableStatuses {
    final statuses = _activeTabTasks
        .map((t) => t.verificationStatus)
        .toSet()
        .toList();
    statuses.sort();
    return ['All', ...statuses];
  }

  List<String> get _availableResults {
    final results = _activeTabTasks
        .map((t) => t.inspectionResult ?? 'Pending')
        .toSet()
        .toList();
    results.sort();
    return ['All', ...results];
  }

  List<String> get _availableBarangays {
    final barangays = _activeTabTasks
        .map((t) => t.barangayName)
        .toSet()
        .toList();
    barangays.sort();
    return ['All', ...barangays];
  }

  void _validateFilters() {
    if (_selectedStatus != 'All' &&
        !_availableStatuses.contains(_selectedStatus)) {
      _selectedStatus = 'All';
    }
    if (_selectedResult != 'All' &&
        !_availableResults.contains(_selectedResult)) {
      _selectedResult = 'All';
    }
    if (_selectedBarangay != 'All' &&
        !_availableBarangays.contains(_selectedBarangay)) {
      _selectedBarangay = 'All';
    }
  }

  String _formatResult(String result) {
    switch (result) {
      case 'Green':
        return 'Registered';
      case 'Yellow':
        return 'Suspected / Needs Verification';
      case 'Orange':
        return 'Warned / Non-Compliant';
      case 'Red':
        return 'Unregistered';
      case 'Black':
        return 'Blacklisted / Non-Responsive';
      case 'Purple':
        return 'Closed / Abandoned';
      default:
        return result;
    }
  }

  List<InspectionTask> _applyFiltersAndSort(
    List<InspectionTask> tasks,
    bool isHistory,
  ) {
    final q = _searchQuery.toLowerCase();
    var filtered = tasks.where((t) {
      final matchesSearch =
          q.isEmpty ||
          t.detectedName.toLowerCase().contains(q) ||
          t.barangayName.toLowerCase().contains(q);
      final matchesBarangay =
          _selectedBarangay == 'All' || t.barangayName == _selectedBarangay;

      if (!isHistory) {
        return matchesSearch && matchesBarangay;
      } else {
        final matchesStatus =
            _selectedStatus == 'All' || t.verificationStatus == _selectedStatus;
        final matchesResult =
            _selectedResult == 'All' ||
            (t.inspectionResult ?? 'Pending') == _selectedResult;
        return matchesSearch &&
            matchesBarangay &&
            matchesStatus &&
            matchesResult;
      }
    }).toList();

    if (!isHistory) {
      filtered.sort((a, b) {
        final dateA =
            DateTime.tryParse(a.irTimestamp) ??
            DateTime.fromMillisecondsSinceEpoch(0);
        final dateB =
            DateTime.tryParse(b.irTimestamp) ??
            DateTime.fromMillisecondsSinceEpoch(0);
        return _selectedSort == 'Oldest'
            ? dateA.compareTo(dateB)
            : dateB.compareTo(dateA);
      });
    }

    return filtered;
  }

  List<InspectionTask> get _filteredCurrentTasks =>
      _applyFiltersAndSort(_currentTasks, false);
  List<InspectionTask> get _filteredMissingTasks =>
      _applyFiltersAndSort(_missingTasks, false);
  List<InspectionTask> get _filteredHistoryTasks =>
      _applyFiltersAndSort(_historyTasks, true);
  String? _currentError;
  String? _historyError;
  bool _isDrawerOpen = false;
  final InspectionService _inspectionService = InspectionService();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() {
      if (!mounted) return;
      if (_currentFilterIndex != _tabController.index) {
        setState(() {
          _currentFilterIndex = _tabController.index;
          _selectedStatus = 'All';
          _selectedResult = 'All';
          _selectedBarangay = 'All';
          _selectedSort = 'Newest';
        });
      }
    });
    unawaited(_fetchCurrent());
    unawaited(_fetchHistory());
    unawaited(_inspectionService.refreshPendingDraftStatuses());
    _inspectionService.syncNotification.addListener(_showSyncNotification);
    _startRefreshTimer();
  }

  void _startRefreshTimer() {
    _refreshTimer ??= Timer.periodic(const Duration(seconds: 10), (_) {
      unawaited(_fetchCurrent(silent: true));
      unawaited(_fetchHistory(silent: true));
    });
  }

  void _stopRefreshTimer() {
    _refreshTimer?.cancel();
    _refreshTimer = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _startRefreshTimer();
      unawaited(_fetchCurrent(silent: true));
      unawaited(_fetchHistory(silent: true));
    } else if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _stopRefreshTimer();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stopRefreshTimer();
    _inspectionService.syncNotification.removeListener(_showSyncNotification);
    _searchController.dispose();
    _tabController.dispose();
    super.dispose();
  }

  void _showSyncNotification() {
    if (!mounted) return;
    final event = _inspectionService.syncNotification.value;
    if (event == null) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          event.started
              ? 'Connection restored. Syncing offline reports...'
              : '${event.syncedCount} Offline report${event.syncedCount == 1 ? '' : 's'} successfully submitted to Admin.',
        ),
        backgroundColor: Colors.green.shade700,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _fetchCurrent({bool silent = false}) async {
    final hasCachedTasks = _currentTasks.isNotEmpty || _missingTasks.isNotEmpty;
    if (!silent && mounted) {
      setState(() {
        _loadingCurrent = true;
        _currentError = null;
      });
    }
    try {
      var tasks = await _inspectionService.getMyTasks();

      // Dashboard keeps its last known assignments while a resumed request is
      // settling. Use the same account-scoped cache here so the Current tab
      // never becomes empty merely because one API response is delayed/empty.
      if (tasks.isEmpty) {
        final userId = await AuthService().getAuthenticatedUserId();
        final cached = await _inspectionService.getLocalTasksForUser(
          userId,
          activeOnly: true,
        );
        if (cached.isNotEmpty) tasks = cached;
      }

      final activeTasks = tasks
          .where(
            (task) => _activeStatuses.contains(
              task.verificationStatus.trim().toLowerCase(),
            ),
          )
          .toList();

      // A malformed/missing status should not make a valid task returned by
      // the active-task endpoint disappear from Current. The endpoint itself
      // already guarantees Assigned/Reassigned reports only.
      final displayTasks = activeTasks.isEmpty && tasks.isNotEmpty
          ? tasks
          : activeTasks;

      final now = DateTime.now();
      final currentList = <InspectionTask>[];
      final missingList = <InspectionTask>[];

      for (var t in displayTasks) {
        if (t.deadline != null && t.deadline!.isNotEmpty) {
          final dl = DateTime.tryParse(t.deadline!);
          if (dl != null && dl.isBefore(now)) {
            missingList.add(t);
            continue;
          }
        }
        currentList.add(t);
      }

      if (mounted) {
        setState(() {
          if (currentList.isNotEmpty || !hasCachedTasks) {
            _currentTasks = currentList;
            _missingTasks = missingList;
          }
          if (_currentFilterIndex == 0 || _currentFilterIndex == 1) {
            _validateFilters();
          }
          _loadingCurrent = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _currentError = hasCachedTasks
              ? null
              : 'Unable to load your tasks. Please pull down to refresh.';
          _loadingCurrent = false;
        });
      }
    }
  }

  Future<void> _fetchHistory({bool silent = false}) async {
    final hasCachedTasks = _historyTasks.isNotEmpty;
    if (!silent && mounted) {
      setState(() {
        _loadingHistory = true;
        _historyError = null;
      });
    }
    try {
      final all = await InspectionService().getMyReportHistory();
      final historyTasks = all
          .where((t) => !_activeStatuses.contains(t.verificationStatus))
          .toList();
      if (mounted) {
        setState(() {
          _historyTasks = historyTasks;
          if (_currentFilterIndex == 2) {
            _validateFilters();
          }
          _loadingHistory = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _historyError = hasCachedTasks
              ? null
              : 'Unable to load your inspection history. Please pull down to refresh.';
          _loadingHistory = false;
        });
      }
    }
  }

  // Tapping a CURRENT item opens the interactive InspectionModal to conduct report
  void _onCurrentTaskTap(InspectionTask task) async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => InspectionModal(
        task: task,
        onSubmitted: () {
          _fetchCurrent();
          _fetchHistory();
        },
      ),
    );
    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  // Tapping a HISTORY item navigates to HistoryDetailPage
  void _onHistoryTaskTap(InspectionTask task) async {
    if (_isDrawerOpen) return;
    setState(() => _isDrawerOpen = true);
    widget.onDrawerToggled?.call(true);

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => HistoryDetailPage(task: task),
    );

    widget.onDrawerToggled?.call(false);
    if (mounted) setState(() => _isDrawerOpen = false);
  }

  Widget _buildDropdownColumn({
    required String label,
    required String value,
    required List<String> items,
    required ValueChanged<String?> onChanged,
    String Function(String)? formatValue,
  }) {
    // Defensive check to avoid Flutter DropdownButton crash
    // Ensure items are strictly unique and the value exists in the list.
    final safeItems = items.toSet().toList();
    final safeValue = safeItems.contains(value)
        ? value
        : (safeItems.isNotEmpty ? safeItems.first : null);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.bold,
            color: Colors.grey,
          ),
        ),
        const SizedBox(height: 4),
        Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: context.isDarkMode ? Colors.grey[800] : Colors.grey[100],
            borderRadius: BorderRadius.circular(8),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              value: safeValue,
              icon: const Icon(
                Icons.keyboard_arrow_down_rounded,
                color: Colors.grey,
                size: 18,
              ),
              style: TextStyle(
                color: context.adaptiveTextDark,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
              dropdownColor: context.adaptiveSurface,
              onChanged: onChanged,
              items: safeItems.map<DropdownMenuItem<String>>((String item) {
                final text = formatValue != null
                    ? formatValue(item)
                    : (item == 'All' ? 'All $label' : item);
                return DropdownMenuItem<String>(
                  value: item,
                  child: Text(text, overflow: TextOverflow.ellipsis),
                );
              }).toList(),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildFilter(BuildContext context) {
    final isHistory = _currentFilterIndex == 2;

    final statuses = _availableStatuses;
    final results = _availableResults;
    final barangays = _availableBarangays;

    final hasStatusFilter = statuses.length > 1;
    final hasResultFilter = results.length > 1;
    final hasBarangayFilter = barangays.length > 1;

    // Check if we have anything to show
    if (isHistory &&
        !hasStatusFilter &&
        !hasResultFilter &&
        !hasBarangayFilter) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: context.adaptiveSurface,
          borderRadius: BorderRadius.circular(16),
          border: context.isDarkMode
              ? Border.all(color: Colors.grey.shade800)
              : Border.all(color: Colors.grey.shade200),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.05),
              blurRadius: 10,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Filters',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: context.adaptiveTextDark,
                  ),
                ),
                if (_selectedStatus != 'All' ||
                    _selectedResult != 'All' ||
                    _selectedBarangay != 'All' ||
                    _selectedSort != 'Newest')
                  GestureDetector(
                    onTap: () {
                      if (mounted) {
                        setState(() {
                          _selectedStatus = 'All';
                          _selectedResult = 'All';
                          _selectedBarangay = 'All';
                          _selectedSort = 'Newest';
                        });
                      }
                    },
                    child: Text(
                      'Clear',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: context.adaptivePrimary,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            if (!isHistory)
              Row(
                children: [
                  if (hasBarangayFilter)
                    Expanded(
                      child: _buildDropdownColumn(
                        label: 'Barangay',
                        value: _selectedBarangay,
                        items: barangays,
                        onChanged: (val) =>
                            setState(() => _selectedBarangay = val!),
                      ),
                    ),
                  if (hasBarangayFilter) const SizedBox(width: 12),
                  Expanded(
                    child: _buildDropdownColumn(
                      label: 'Sort',
                      value: _selectedSort,
                      items: const ['Newest', 'Oldest'],
                      onChanged: (val) => setState(() => _selectedSort = val!),
                    ),
                  ),
                ],
              ),
            if (isHistory) ...[
              if (isHistory && hasBarangayFilter)
                Row(
                  children: [
                    Expanded(
                      child: _buildDropdownColumn(
                        label: 'Barangay',
                        value: _selectedBarangay,
                        items: barangays,
                        onChanged: (val) =>
                            setState(() => _selectedBarangay = val!),
                      ),
                    ),
                  ],
                ),
              if (hasBarangayFilter && (hasStatusFilter || hasResultFilter))
                const SizedBox(height: 12),
              Row(
                children: [
                  if (hasStatusFilter)
                    Expanded(
                      child: _buildDropdownColumn(
                        label: 'Status',
                        value: _selectedStatus,
                        items: statuses,
                        onChanged: (val) =>
                            setState(() => _selectedStatus = val!),
                      ),
                    ),
                  if (hasStatusFilter && hasResultFilter)
                    const SizedBox(width: 12),
                  if (hasResultFilter)
                    Expanded(
                      child: _buildDropdownColumn(
                        label: 'Result',
                        value: _selectedResult,
                        items: results,
                        onChanged: (val) =>
                            setState(() => _selectedResult = val!),
                        formatValue: (val) =>
                            val == 'All' ? 'All' : _formatResult(val),
                      ),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildShimmerLoader(BuildContext context) {
    return ListView.builder(
      padding: const EdgeInsets.all(20),
      itemCount: 4,
      itemBuilder: (context, index) => Padding(
        padding: const EdgeInsets.only(bottom: 16.0),
        child: Shimmer.fromColors(
          baseColor: context.isDarkMode ? Colors.grey[800]! : Colors.grey[300]!,
          highlightColor: context.isDarkMode
              ? Colors.grey[700]!
              : Colors.grey[100]!,
          child: Container(
            height: 120,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: CustomAppBar(
        title: 'Inspections',
        icon: Icons.assignment_turned_in_rounded,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12.0),
            child: Container(
              decoration: BoxDecoration(
                color: context.isDarkMode ? Colors.grey[800] : Colors.grey[100],
                borderRadius: BorderRadius.circular(16),
              ),
              child: IconButton(
                icon: Icon(
                  Icons.sync_rounded,
                  color: context.isDarkMode
                      ? Colors.white
                      : AppColors.darkGreen,
                  size: 22,
                ),
                tooltip: 'Sync pending reports',
                onPressed: () async {
                  // Capture the messenger before any async gap so `context`
                  // is never used across one (use_build_context_synchronously).
                  final messenger = ScaffoldMessenger.of(context);
                  final pendingCount = await InspectionService()
                      .getPendingDraftCount();
                  if (!mounted) return;
                  if (pendingCount == 0) {
                    messenger.showSnackBar(
                      const SnackBar(
                        content: Text('No pending reports to sync.'),
                      ),
                    );
                    return;
                  }
                  final syncedCount = await InspectionService()
                      .syncPendingReports();
                  if (!mounted) return;
                  messenger.showSnackBar(
                    SnackBar(
                      content: Text('Synced $syncedCount pending report(s).'),
                    ),
                  );
                },
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(right: 24.0),
            child: Container(
              decoration: BoxDecoration(
                color: context.isDarkMode ? Colors.grey[800] : Colors.grey[100],
                borderRadius: BorderRadius.circular(16),
              ),
              child: Showcase(
                key: MainLayout.tasksPdfTourKey,
                title: 'Notice Generator',
                description:
                    'Tap here to generate and print official PDF notices.',
                targetPadding: const EdgeInsets.all(4),
                child: IconButton(
                  icon: Icon(
                    Icons.picture_as_pdf_rounded,
                    color: context.isDarkMode
                        ? Colors.white
                        : AppColors.darkGreen,
                    size: 24,
                  ),
                  tooltip: 'Generate Notice PDF',
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const PdfGeneratorPage()),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: 20.0,
                vertical: 8.0,
              ),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                decoration: BoxDecoration(
                  color: context.isDarkMode
                      ? Colors.grey[800]
                      : Colors.grey[100],
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Row(
                  children: [
                    Icon(Icons.search, color: Colors.grey),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Showcase(
                        key: MainLayout.tasksSearchTourKey,
                        title: 'Search Assignments',
                        description:
                            'Find specific establishments or barangays quickly.',
                        targetPadding: const EdgeInsets.all(4),
                        child: TextField(
                          controller: _searchController,
                          onChanged: (val) {
                            setState(() {
                              _searchQuery = val;
                            });
                          },
                          style: TextStyle(color: context.adaptiveTextDark),
                          decoration: const InputDecoration(
                            hintText: 'Search establishments or barangay...',
                            hintStyle: TextStyle(color: Colors.grey),
                            border: InputBorder.none,
                            isDense: true,
                            contentPadding: EdgeInsets.symmetric(vertical: 14),
                          ),
                        ),
                      ),
                    ),
                    if (_searchQuery.isNotEmpty)
                      GestureDetector(
                        onTap: () {
                          _searchController.clear();
                          setState(() {
                            _searchQuery = '';
                          });
                        },
                        child: Icon(Icons.close, color: Colors.grey, size: 20),
                      ),
                    const SizedBox(width: 12),
                    Showcase(
                      key: MainLayout.tasksFilterTourKey,
                      title: 'Filters',
                      description:
                          'Tap here to refine your tasks by status, result, or barangay.',
                      targetPadding: const EdgeInsets.all(4),
                      child: GestureDetector(
                        onTap: () {
                          setState(() {
                            _showFilters = !_showFilters;
                          });
                        },
                        child: Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(
                            color: _showFilters
                                ? context.adaptivePrimary.withValues(alpha: 0.1)
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Icon(
                            Icons.tune_rounded,
                            color: _showFilters
                                ? context.adaptivePrimary
                                : Colors.grey,
                            size: 20,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Showcase(
              key: MainLayout.tasksTabsTourKey,
              title: 'Task Categories',
              description:
                  'Switch between Current assignments, Missing tasks, and your inspection History.',
              targetPadding: const EdgeInsets.all(4),
              child: ModernSegmentedFilter(
                options: const ['Current', 'Missing', 'History'],
                selectedIndex: _currentFilterIndex,
                onSelected: (index) {
                  _tabController.animateTo(index);
                },
              ),
            ),
            if (_showFilters) _buildFilter(context),
            const SizedBox(height: 8),
            Expanded(
              child: TabBarView(
                controller: _tabController,
                children: [
                  // ── CURRENT Tab
                  RefreshIndicator(
                    color: context.adaptivePrimary,
                    onRefresh: _fetchCurrent,
                    child: _loadingCurrent
                        ? _buildShimmerLoader(context)
                        : _currentError != null
                        ? _ErrorState(
                            message: _currentError!,
                            onRetry: _fetchCurrent,
                          )
                        : _filteredCurrentTasks.isEmpty
                        ? const _EmptyState(
                            message: 'No current assignments.',
                            imagePath: 'assets/images/searching.png',
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(20),
                            itemCount: _filteredCurrentTasks.length,
                            itemBuilder: (_, i) => TaskCard(
                              task: _filteredCurrentTasks[i],
                              isCurrent: true,
                              onTap: () =>
                                  _onCurrentTaskTap(_filteredCurrentTasks[i]),
                            ),
                          ),
                  ),

                  // ── MISSING Tab ──────────────────────────────────────────────────
                  RefreshIndicator(
                    color: context.adaptivePrimary,
                    onRefresh: _fetchCurrent,
                    child: _loadingCurrent
                        ? _buildShimmerLoader(context)
                        : _currentError != null
                        ? _ErrorState(
                            message: _currentError!,
                            onRetry: _fetchCurrent,
                          )
                        : _filteredMissingTasks.isEmpty
                        ? const _EmptyState(
                            message: 'No missing assignments.',
                            imagePath: 'assets/images/searching.png',
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(20),
                            itemCount: _filteredMissingTasks.length,
                            itemBuilder: (_, i) => TaskCard(
                              task: _filteredMissingTasks[i],
                              isCurrent: true,
                              isMissing: true,
                              onTap: () =>
                                  _onCurrentTaskTap(_filteredMissingTasks[i]),
                            ),
                          ),
                  ),

                  // ── HISTORY Tab ──────────────────────────────────────────────────
                  RefreshIndicator(
                    color: context.adaptivePrimary,
                    onRefresh: _fetchHistory,
                    child: _loadingHistory
                        ? _buildShimmerLoader(context)
                        : _historyError != null
                        ? _ErrorState(
                            message: _historyError!,
                            onRetry: _fetchHistory,
                          )
                        : _historyTasks.isEmpty
                        ? const _EmptyState(
                            message: 'No inspection history yet.',
                            imagePath: 'assets/images/searching.png',
                          )
                        : _filteredHistoryTasks.isEmpty
                        ? const _EmptyState(
                            message: 'No history matches the selected filter.',
                            imagePath: 'assets/images/searching.png',
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(20),
                            itemCount: _filteredHistoryTasks.length,
                            itemBuilder: (_, i) => TaskCard(
                              task: _filteredHistoryTasks[i],
                              isCurrent: false,
                              onTap: () =>
                                  _onHistoryTaskTap(_filteredHistoryTasks[i]),
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
}

// ─── Empty State ──────────────────────────────────────────────────────────────
class _EmptyState extends StatelessWidget {
  final String message;
  final String? imagePath;

  const _EmptyState({required this.message, this.imagePath});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (imagePath != null)
            FloatingMascot(imagePath: imagePath!, height: 160),
          const SizedBox(height: 16),
          Text(
            message,
            style: TextStyle(
              color: Colors.grey[400],
              fontSize: 16,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Error State ──────────────────────────────────────────────────────────────
class _ErrorState extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorState({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.wifi_off, color: Colors.grey, size: 40),
          SizedBox(height: 12),
          Text(message, style: TextStyle(color: Colors.grey)),
          SizedBox(height: 12),
          TextButton(onPressed: onRetry, child: Text('Retry')),
        ],
      ),
    );
  }
}
