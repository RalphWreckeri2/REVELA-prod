import 'package:intl/intl.dart';

class AppDateUtils {
  AppDateUtils._();

  static final _deadlineFmt = DateFormat('MMM d, yyyy');
  static final _timestampFmt = DateFormat("MMM d · h:mm a");
  static final _shortFmt = DateFormat('MMM d, yyyy');

  /// Formats an ISO deadline string → "Jul 16, 2025"
  static String formatDeadline(String? raw) {
    if (raw == null || raw.isEmpty) return 'No deadline';
    try {
      final dt = DateTime.parse(raw).toLocal();
      return _deadlineFmt.format(dt);
    } catch (_) {
      return raw;
    }
  }

  /// Formats an ISO timestamp → "Jul 16 · 8:00 AM"
  static String formatTimestamp(String? raw) {
    if (raw == null || raw.isEmpty) return '';
    try {
      final dt = DateTime.parse(raw).toLocal();
      return _timestampFmt.format(dt);
    } catch (_) {
      return raw;
    }
  }

  /// Formats an ISO timestamp as a relative label → "2 days ago", "Just now", etc.
  static String formatRelative(String? raw) {
    if (raw == null || raw.isEmpty) return '';
    try {
      final dt = DateTime.parse(raw).toLocal();
      final now = DateTime.now();
      final diff = now.difference(dt);

      if (diff.inSeconds < 60) return 'Just now';
      if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
      if (diff.inHours < 24) return '${diff.inHours}h ago';
      if (diff.inDays == 1) return 'Yesterday';
      if (diff.inDays < 7) return '${diff.inDays} days ago';
      return _shortFmt.format(dt);
    } catch (_) {
      return raw;
    }
  }
}
