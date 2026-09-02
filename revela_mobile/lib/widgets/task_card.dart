import 'package:flutter/material.dart';
import '../service/inspection_service.dart';
import '../service/offline_inspection_storage.dart';
import '../theme/app_theme.dart';
import '../widgets/scale_tap.dart';
import '../utils/date_utils.dart';

class TaskCard extends StatelessWidget {
  final InspectionTask task;
  final bool isCurrent;
  final bool isMissing;
  final VoidCallback onTap;

  const TaskCard({
    super.key,
    required this.task,
    required this.isCurrent,
    this.isMissing = false,
    required this.onTap,
  });

  Color _flagColor() {
    switch (task.flagColor.toLowerCase()) {
      case 'red':
        return Colors.redAccent;
      case 'yellow':
        return const Color(0xFFF59E0B);
      case 'orange':
        return const Color(0xFFE65100);
      case 'green':
        return const Color(0xFF10B981);
      case 'black':
        return const Color(0xFF1E293B);
      case 'purple':
        return const Color(0xFF7C3AED);
      default:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    bool isNearing = false;
    bool actualIsMissing = isMissing;

    if (task.deadline != null && task.deadline!.isNotEmpty) {
      try {
        final deadline = AppDateUtils.parseToLocal(task.deadline!);
        if (deadline != null) {
          if (deadline.isBefore(DateTime.now())) {
            actualIsMissing = true;
          } else {
            final diff = deadline.difference(DateTime.now());
            if (diff.inHours <= 24 && !diff.isNegative) {
              isNearing = true;
            }
          }
        }
      } catch (_) {}
    }

    if (!isCurrent) {
      actualIsMissing = false;
      isNearing = false;
    }

    final Color accentColor = actualIsMissing
        ? Colors.redAccent
        : isNearing
        ? const Color(0xFFF59E0B)
        : isCurrent
        ? _flagColor()
        : Colors.grey;

    return ScaleTap(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(
          color: context.adaptiveSurface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: context.isDarkMode
                ? Colors.grey.shade800
                : Colors.grey.shade200,
            width: 0.5,
          ),
          boxShadow: [
            BoxShadow(
              blurRadius: 8,
              color: Colors.black.withValues(alpha: 0.06),
              offset: const Offset(0, 2),
            ),
          ],
        ),
        clipBehavior: Clip.antiAlias,
        child: Container(
          decoration: BoxDecoration(
            border: Border(left: BorderSide(color: accentColor, width: 4)),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 14, 16, 14),
            child: Row(
              children: [
                // Icon badge
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: accentColor.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(
                    isCurrent || actualIsMissing
                        ? Icons.storefront_outlined
                        : Icons.assignment_turned_in_outlined,
                    color: accentColor,
                    size: 22,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        task.detectedName,
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                          color: context.adaptiveTextDark,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 3),
                      Text(
                        task.barangayName,
                        style: TextStyle(
                          fontSize: 12,
                          color: context.adaptiveTextMid,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          Icon(
                            Icons.calendar_today_outlined,
                            size: 11,
                            color: isNearing
                                ? const Color(0xFFF59E0B)
                                : context.adaptiveTextLight,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            (task.deadline != null && task.deadline!.isNotEmpty)
                                ? 'Due ${AppDateUtils.formatDeadline(task.deadline)}'
                                : AppDateUtils.formatTimestamp(
                                    task.irTimestamp,
                                  ),
                            style: TextStyle(
                              fontSize: 11,
                              color: isNearing
                                  ? const Color(0xFFF59E0B)
                                  : context.adaptiveTextLight,
                            ),
                          ),
                        ],
                      ),
                      ValueListenableBuilder<Map<int, DraftStatus>>(
                        valueListenable:
                            InspectionService().pendingDraftStatuses,
                        builder: (context, statuses, _) {
                          final status = statuses[task.logID];
                          if (status == null) return const SizedBox.shrink();
                          final syncing = status == DraftStatus.syncing;
                          return Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: _StatusBadge(
                              label: syncing ? 'SYNCING...' : 'PENDING SYNC',
                              color: syncing
                                  ? Colors.blue
                                  : Colors.orange.shade700,
                              icon: syncing
                                  ? Icons.sync
                                  : Icons.cloud_queue_rounded,
                              spinning: syncing,
                            ),
                          );
                        },
                      ),
                      if (actualIsMissing) ...[
                        const SizedBox(height: 6),
                        _StatusBadge(label: 'OVERDUE', color: Colors.redAccent),
                      ] else if (isNearing) ...[
                        const SizedBox(height: 6),
                        _StatusBadge(
                          label: 'DUE SOON',
                          color: const Color(0xFFF59E0B),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Icon(
                  isCurrent
                      ? Icons.chevron_right_rounded
                      : Icons.chevron_right_rounded,
                  color: context.adaptiveTextLight,
                  size: 20,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String label;
  final Color color;
  final IconData? icon;
  final bool spinning;
  const _StatusBadge({
    required this.label,
    required this.color,
    this.icon,
    this.spinning = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.4), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            spinning
                ? SizedBox(
                    width: 11,
                    height: 11,
                    child: CircularProgressIndicator(
                      strokeWidth: 1.5,
                      color: color,
                    ),
                  )
                : Icon(icon, size: 12, color: color),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.bold,
              color: color,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
