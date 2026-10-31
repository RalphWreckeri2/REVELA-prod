import 'dart:async';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'auth_service.dart';

class InAppNotification {
  final int id;
  final String type;
  final String title;
  final String body;
  final String? readAt;
  final String createdAt;

  InAppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    this.readAt,
    required this.createdAt,
  });

  bool get isUnread => readAt == null || readAt!.isEmpty;

  factory InAppNotification.fromJson(Map<String, dynamic> json) {
    return InAppNotification(
      id: json['id'] is int
          ? json['id'] as int
          : int.tryParse(json['id']?.toString() ?? '') ?? 0,
      type: json['type']?.toString() ?? '',
      title: json['title']?.toString() ?? '',
      body: json['body']?.toString() ?? '',
      readAt: json['readAt']?.toString(),
      createdAt: json['createdAt']?.toString() ?? '',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'type': type,
      'title': title,
      'body': body,
      'readAt': readAt,
      'createdAt': createdAt,
    };
  }
}

class InAppNotificationPage {
  final List<InAppNotification> notifications;
  final int total;
  final int unreadCount;
  final bool isOffline;

  const InAppNotificationPage({
    required this.notifications,
    required this.total,
    required this.unreadCount,
    this.isOffline = false,
  });
}

class InAppNotificationsService {
  static final InAppNotificationsService _instance =
      InAppNotificationsService._internal();
  factory InAppNotificationsService() => _instance;
  InAppNotificationsService._internal();

  Dio get _dio => AuthService().dio;
  static const String _cacheKey = 'cached_in_app_notifications_list';
  static const int pageSize = 10;

  /// Reactive unread count listener for app bar / bottom nav bar badges.
  final ValueNotifier<int> unreadCountNotifier = ValueNotifier<int>(0);

  Future<InAppNotificationPage> fetchNotifications({
    int limit = pageSize,
    int offset = 0,
  }) async {
    try {
      final response = await _dio.get(
        '/api/notifications',
        queryParameters: {'limit': limit, 'offset': offset},
      );
      final List<dynamic> data = response.data['data'] ?? [];
      final list = data
          .map((e) => InAppNotification.fromJson(e as Map<String, dynamic>))
          .toList();
      final total = _parseCount(response.data['total'], list.length);
      final unread = _parseCount(
        response.data['unreadCount'],
        list.where((n) => n.isUnread).length,
      );
      unreadCountNotifier.value = unread;

      // Save to local storage for offline access
      unawaited(_cacheNotificationsLocally(data));

      return InAppNotificationPage(
        notifications: list,
        total: total,
        unreadCount: unread,
      );
    } catch (e) {
      debugPrint(
        '[NOTIFICATIONS] Network fetch failed: $e. Using offline cached notifications.',
      );
      final cached = await loadCachedNotifications();
      if (cached.isNotEmpty) {
        final unreadCount = cached.where((n) => n.isUnread).length;
        final start = offset.clamp(0, cached.length);
        final end = (offset + limit).clamp(start, cached.length);
        unreadCountNotifier.value = unreadCount;
        return InAppNotificationPage(
          notifications: cached.sublist(start, end),
          total: cached.length,
          unreadCount: unreadCount,
          isOffline: true,
        );
      }
      rethrow;
    }
  }

  int _parseCount(dynamic value, int fallback) {
    if (value is int && value >= 0) return value;
    final parsed = int.tryParse(value?.toString() ?? '');
    return parsed != null && parsed >= 0 ? parsed : fallback;
  }

  Future<void> _cacheNotificationsLocally(List<dynamic> rawData) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final existingJson = prefs.getString(_cacheKey);
      final existing = existingJson == null
          ? <dynamic>[]
          : jsonDecode(existingJson) as List<dynamic>;
      final notificationsById = <int, Map<String, dynamic>>{};
      for (final item in [...existing, ...rawData]) {
        final notification = Map<String, dynamic>.from(item as Map);
        final id = _parseCount(notification['id'], 0);
        if (id > 0) notificationsById[id] = notification;
      }
      final notifications = notificationsById.values.toList()
        ..sort((a, b) {
          final createdAt = (b['createdAt']?.toString() ?? '').compareTo(
            a['createdAt']?.toString() ?? '',
          );
          if (createdAt != 0) return createdAt;
          return _parseCount(b['id'], 0).compareTo(_parseCount(a['id'], 0));
        });
      await prefs.setString(
        _cacheKey,
        jsonEncode(notifications.take(50).toList()),
      );
    } catch (e) {
      debugPrint('[NOTIFICATIONS] Cache save error: $e');
    }
  }

  Future<List<InAppNotification>> loadCachedNotifications() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_cacheKey);
      if (raw != null && raw.isNotEmpty) {
        final List<dynamic> decoded = jsonDecode(raw);
        return decoded
            .map((e) => InAppNotification.fromJson(e as Map<String, dynamic>))
            .toList();
      }
    } catch (e) {
      debugPrint('[NOTIFICATIONS] Cache read error: $e');
    }
    return [];
  }

  Future<int> fetchUnreadCount() async {
    try {
      final response = await _dio.get('/api/notifications/unread-count');
      final n = response.data['count'];
      final count = (n is int) ? n : (int.tryParse(n?.toString() ?? '') ?? 0);
      unreadCountNotifier.value = count;
      return count;
    } catch (_) {
      return unreadCountNotifier.value;
    }
  }

  Future<void> markAllRead() async {
    try {
      await _dio.patch('/api/notifications/read', data: <String, dynamic>{});
    } catch (_) {}
    unreadCountNotifier.value = 0;
  }

  Future<void> markRead(List<int> ids) async {
    try {
      await _dio.patch('/api/notifications/read', data: {'ids': ids});
    } catch (_) {}
    unreadCountNotifier.value = (unreadCountNotifier.value - ids.length).clamp(
      0,
      9999,
    );
  }

  Future<void> deleteNotification(int id) async {
    try {
      await _dio.delete(
        '/api/notifications',
        data: {
          'ids': [id],
        },
      );
    } catch (_) {}
  }

  Future<void> deleteAllNotifications() async {
    try {
      await _dio.delete('/api/notifications', data: {});
    } catch (_) {}
    unreadCountNotifier.value = 0;
  }
}
