import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

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
}

class InAppNotificationsService {
  static final InAppNotificationsService _instance =
      InAppNotificationsService._internal();
  factory InAppNotificationsService() => _instance;
  InAppNotificationsService._internal();

  Dio get _dio => AuthService().dio;

  /// Reactive unread count listener for app bar / bottom nav bar badges.
  final ValueNotifier<int> unreadCountNotifier = ValueNotifier<int>(0);

  Future<List<InAppNotification>> fetchNotifications() async {
    final response = await _dio.get('/api/notifications');
    final List<dynamic> data = response.data['data'] ?? [];
    final list = data
        .map((e) => InAppNotification.fromJson(e as Map<String, dynamic>))
        .toList();
    final unread = list.where((n) => n.isUnread).length;
    unreadCountNotifier.value = unread;
    return list;
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
    await _dio.patch('/api/notifications/read', data: <String, dynamic>{});
    unreadCountNotifier.value = 0;
  }

  Future<void> markRead(List<int> ids) async {
    await _dio.patch('/api/notifications/read', data: {'ids': ids});
    unreadCountNotifier.value =
        (unreadCountNotifier.value - ids.length).clamp(0, 9999);
  }

  Future<void> deleteNotification(int id) async {
    await _dio.delete('/api/notifications', data: {'ids': [id]});
  }

  Future<void> deleteAllNotifications() async {
    await _dio.delete('/api/notifications', data: {});
    unreadCountNotifier.value = 0;
  }
}
