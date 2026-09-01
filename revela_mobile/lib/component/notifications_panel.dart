import 'package:flutter/material.dart';
import '../service/in_app_notifications_service.dart';
import '../service/inspection_service.dart';
import '../theme/app_theme.dart';

class NotificationsPanel extends StatefulWidget {
  final List<InspectionTask> activeTasks;
  final void Function(InspectionTask) onTaskTap;

  const NotificationsPanel({
    super.key,
    required this.activeTasks,
    required this.onTaskTap,
  });

  @override
  State<NotificationsPanel> createState() => _NotificationsPanelState();
}

class _NotificationsPanelState extends State<NotificationsPanel> {
  List<InAppNotification> _items = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await InAppNotificationsService().fetchNotifications();
      if (mounted) {
        setState(() {
          _items = list;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Could not load notifications.';
          _loading = false;
        });
      }
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

  @override
  Widget build(BuildContext context) {
    final maxH = MediaQuery.of(context).size.height * 0.55;

    return Container(
      constraints: BoxConstraints(maxHeight: maxH),
      decoration: BoxDecoration(
        color: Theme.of(context).brightness == Brightness.dark ? Colors.grey[900] : Colors.white,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(height: 10),
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: Colors.grey[300],
              borderRadius: BorderRadius.circular(8),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 12, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Notifications',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Theme.of(context).brightness == Brightness.dark ? Colors.white : AppColors.textDark,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.mark_email_read_outlined, color: AppColors.darkGreen),
                  tooltip: 'Mark all as read',
                  onPressed: _loading ? null : () async {
                    await InAppNotificationsService().markAllRead();
                    _load();
                  },
                ),
                IconButton(
                  icon: const Icon(Icons.refresh, color: AppColors.darkGreen),
                  onPressed: _loading ? null : _load,
                ),
                IconButton(
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Flexible(
            child: _loading
                ? const Padding(
                    padding: EdgeInsets.all(32),
                    child: Center(
                      child: CircularProgressIndicator(
                        color: AppColors.darkGreen,
                      ),
                    ),
                  )
                : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: Colors.grey),
                      textAlign: TextAlign.center,
                    ),
                  )
                : _items.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(32),
                    child: Text(
                      'No notifications yet.\nNew assignments from admin will appear here.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey, height: 1.5),
                    ),
                  )
                : ListView.separated(
                    shrinkWrap: true,
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                    itemCount: _items.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final n = _items[i];
                      return GestureDetector(
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
                            final reportId = match != null ? int.tryParse(match.group(1) ?? '') : null;
                            if (reportId != null) {
                              InspectionTask? task;
                              for (var t in widget.activeTasks) {
                                if (t.reportID == reportId) {
                                  task = t;
                                  break;
                                }
                              }
                              if (task != null) {
                                widget.onTaskTap(task);
                                return;
                              }
                            }
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('You have already completed this inspection, or it was reassigned.')));
                            }
                          }
                        },
                        child: Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                          color: n.isUnread
                              ? AppColors.darkGreen.withValues(alpha: 0.06)
                              : Theme.of(context).brightness == Brightness.dark ? Colors.grey[800] : Colors.grey[50],
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: n.isUnread
                                ? AppColors.darkGreen.withValues(alpha: 0.25)
                                : Theme.of(context).brightness == Brightness.dark ? Colors.grey.shade700 : Colors.grey.shade200,
                          ),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              _iconForType(n.type),
                              color: AppColors.darkGreen,
                              size: 22,
                            ),
                            const SizedBox(width: 12),
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
                                      color: Theme.of(context).brightness == Brightness.dark ? Colors.white : AppColors.textDark,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    n.body,
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: Colors.grey,
                                      height: 1.4,
                                    ),
                                  ),
                                  if (n.createdAt.isNotEmpty) ...[
                                    const SizedBox(height: 6),
                                    Text(
                                      n.createdAt,
                                      style: TextStyle(
                                        fontSize: 11,
                                        color: Colors.grey[500],
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                  ),
          ),
        ],
      ),
    );
  }
}
