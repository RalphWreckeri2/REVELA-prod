import 'package:intl/intl.dart';

class AppDateUtils {
  AppDateUtils._();

  static final _deadlineFmt = DateFormat('MMM d, yyyy');
  static final _timestampFmt = DateFormat("MMM d · h:mm a");
  static final _shortFmt = DateFormat('MMM d, yyyy');

  /// Parses any ISO or MySQL timestamp string into a local DateTime.
  /// Treats timestamps without explicit timezone offset as UTC (from MySQL).
  static DateTime? parseToLocal(String? raw) {
    if (raw == null || raw.trim().isEmpty) return null;
    final str = raw.trim();

    try {
      // If pure date (YYYY-MM-DD), parse directly as local date
      if (RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(str)) {
        final parts = str.split('-').map(int.parse).toList();
        return DateTime(parts[0], parts[1], parts[2]);
      }

      // If missing timezone indicator ('Z' or '+08:00' / '-05:00'), treat as UTC
      if (!str.toUpperCase().endsWith('Z') &&
          !RegExp(r'[+-]\d{2}:?\d{2}$').hasMatch(str)) {
        final normalized = '${str.replaceAll(' ', 'T')}Z';
        return DateTime.parse(normalized).toLocal();
      }

      return DateTime.parse(str).toLocal();
    } catch (_) {
      try {
        return DateTime.parse(str).toLocal();
      } catch (_) {
        return null;
      }
    }
  }

  /// Formats an ISO deadline string → "Jul 16, 2025"
  static String formatDeadline(String? raw) {
    if (raw == null || raw.isEmpty) return 'No deadline';
    final dt = parseToLocal(raw);
    if (dt == null) return raw;
    return _deadlineFmt.format(dt);
  }

  /// Formats an ISO timestamp → "Jul 16 · 8:00 AM"
  static String formatTimestamp(String? raw) {
    if (raw == null || raw.isEmpty) return '';
    final dt = parseToLocal(raw);
    if (dt == null) return raw;
    return _timestampFmt.format(dt);
  }

  /// Formats an ISO timestamp as a relative label → "2 days ago", "Just now", etc.
  static String formatRelative(String? raw) {
    if (raw == null || raw.isEmpty) return '';
    final dt = parseToLocal(raw);
    if (dt == null) return raw;

    final now = DateTime.now();
    final diff = now.difference(dt);
    final sec = diff.inSeconds;

    if (sec >= 0 && sec < 60 || sec < 0 && sec.abs() < 60) return 'Just now';
    if (diff.inMinutes > 0 && diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours > 0 && diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays == 1) return 'Yesterday';
    if (diff.inDays > 1 && diff.inDays < 7) return '${diff.inDays} days ago';
    return _shortFmt.format(dt);
  }
}
