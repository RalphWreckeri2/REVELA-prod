import 'dart:async';
import 'dart:typed_data';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../pages/notifications_page.dart';
import 'auth_service.dart';
import 'in_app_notifications_service.dart';
import 'inspection_service.dart';
import '../utils/date_utils.dart';
import 'package:timezone/data/latest_all.dart' as tz;
import 'package:timezone/timezone.dart' as tz;

final _channel = AndroidNotificationChannel(
  'revela_inspection_alerts',
  'Inspection alerts',
  description: 'Alerts for inspection assignments and inspection updates.',
  importance: Importance.max,
  playSound: true,
  enableVibration: true,
  vibrationPattern: Int64List.fromList(<int>[0, 300, 180, 300]),
);

final FlutterLocalNotificationsPlugin _localNotifications =
    FlutterLocalNotificationsPlugin();

/// Must be a top-level function. Android starts a separate Dart isolate for
/// data messages while the app is backgrounded or terminated.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    await Firebase.initializeApp();
    await _initializeLocalNotifications();

    // Notification payloads are rendered by Android/iOS while backgrounded.
    // Render data-only messages locally so they are not silently dropped.
    if (message.notification == null) {
      await PushNotifications.showRemoteNotification(message);
    }
  } catch (error, stackTrace) {
    debugPrint('[FIREBASE INIT WARNING] Background handler: $error');
    debugPrintStack(stackTrace: stackTrace);
  }
}

/// Required by flutter_local_notifications when a notification action is
/// invoked while the process is not running.
@pragma('vm:entry-point')
void notificationTapBackground(NotificationResponse response) {
  // Payload handled upon app startup by getNotificationAppLaunchDetails.
}

class PushNotifications {
  PushNotifications._();

  static final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  static bool _initialized = false;
  static String? pendingReportId;
  static final Set<int> _warnedDeadlineTaskIds = {};

  static Future<void> initialize() async {
    if (_initialized) return;

    try {
      await Firebase.initializeApp();
      await _initializeLocalNotifications();

      final permissions = await _messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );
      debugPrint('FCM permission: ${permissions.authorizationStatus}');

      final android = _localNotifications
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >();
      await android?.requestNotificationsPermission();

      // Save FCM token to backend so push notifications can be sent
      unawaited(_saveFcmTokenToBackend());

      // Listen for FCM token refresh and resave to backend
      _messaging.onTokenRefresh.listen((newToken) {
        debugPrint('[FCM] Token refreshed, saving new token to backend');
        unawaited(_saveFcmTokenToBackend());
      });

      FirebaseMessaging.onMessage.listen((message) async {
        await showRemoteNotification(message);
        // Refresh unread count in real-time on foreground message
        unawaited(InAppNotificationsService().fetchUnreadCount());
      });

      FirebaseMessaging.onMessageOpenedApp.listen(_openInspectionAlerts);

      // Covers local notification that launched a terminated app.
      final localLaunch = await _localNotifications
          .getNotificationAppLaunchDetails();
      if (localLaunch?.didNotificationLaunchApp ?? false) {
        final payload = localLaunch?.notificationResponse?.payload;
        if (payload != null && payload.isNotEmpty) {
          pendingReportId = payload;
          _scheduleAlertNavigation(payload);
        }
      }

      // Covers FCM notification that launched a terminated app.
      final initialMessage = await _messaging.getInitialMessage();
      if (initialMessage != null) {
        final reportId = _reportIdFromData(initialMessage.data);
        if (reportId != null && reportId.isNotEmpty) {
          pendingReportId = reportId;
        }
        WidgetsBinding.instance.addPostFrameCallback(
          (_) => _openInspectionAlerts(initialMessage),
        );
      }

      _initialized = true;
    } catch (error, stackTrace) {
      debugPrint(
        '[FIREBASE INIT WARNING] Push notifications unavailable: $error',
      );
      debugPrintStack(stackTrace: stackTrace);
    }
  }

  static void _openInspectionAlerts(RemoteMessage message) {
    final reportId = _reportIdFromData(message.data);
    _scheduleAlertNavigation(reportId);
  }

  static void _scheduleAlertNavigation(String? reportId) {
    if (reportId != null) pendingReportId = reportId;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      final navigator = AuthService.navigatorKey.currentState;
      if (navigator == null) return;

      // Only navigate if user is authenticated
      if (!AuthService().isAuthenticated) return;

      navigator.push(
        MaterialPageRoute(
          builder: (_) => NotificationsPage(initialReportId: reportId),
        ),
      );
    });
  }

  /// Fetch the FCM token from Firebase and save it to the backend.
  /// This allows the backend to send push notifications to this device.
  static Future<bool> _saveFcmTokenToBackend() async {
    try {
      final token = await _messaging.getToken();
      if (token == null || token.isEmpty) {
        debugPrint('[FCM] No FCM token available from Firebase.');
        return false;
      }

      final jwtToken =
          await const FlutterSecureStorage().read(key: 'jwt_token');
      final isAuthenticated =
          AuthService().isAuthenticated ||
          (jwtToken != null && jwtToken.isNotEmpty);

      if (!isAuthenticated) {
        debugPrint(
          '[FCM] User not authenticated yet; FCM token will be registered upon login.',
        );
        return false;
      }

      debugPrint(
        '[FCM] Saving FCM token to backend: ${token.substring(0, token.length > 20 ? 20 : token.length)}...',
      );

      // Save token to backend via authenticated endpoint
      final dio = AuthService().dio;
      final response = await dio.put(
        '/api/auth/fcm-token',
        data: {'fcmToken': token},
      );

      if (response.statusCode == 200) {
        debugPrint('[FCM] FCM token saved successfully to backend');
        return true;
      } else {
        debugPrint(
          '[FCM] Unexpected response saving FCM token: ${response.statusCode}',
        );
        return false;
      }
    } catch (error, stackTrace) {
      debugPrint('[FCM ERROR] Failed to save FCM token: $error');
      debugPrintStack(stackTrace: stackTrace);
      return false;
    }
  }

  /// Public method to manually refresh and save the FCM token.
  /// Call this after login to ensure the backend has a valid token.
  static Future<bool> refreshFcmToken() async {
    debugPrint('[FCM] Manually refreshing and registering FCM token');
    return await _saveFcmTokenToBackend();
  }

  /// Show a local notification for an incoming remote message.
  static Future<void> showRemoteNotification(RemoteMessage message) async {
    final notification = message.notification;
    final title =
        notification?.title ?? message.data['title'] ?? 'REVELA Update';
    final body =
        notification?.body ??
        message.data['body'] ??
        'You have a new inspection alert.';

    final reportId = _reportIdFromData(message.data);
    final notificationId =
        ((message.messageId?.hashCode ??
            DateTime.now().millisecondsSinceEpoch) &
        0x7FFFFFFF);

    await _localNotifications.show(
      notificationId,
      title,
      body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          _channel.id,
          _channel.name,
          channelDescription: _channel.description,
          importance: Importance.max,
          priority: Priority.high,
          playSound: true,
          enableVibration: true,
          vibrationPattern: Int64List.fromList(<int>[0, 300, 180, 300]),
          icon: '@mipmap/ic_launcher',
        ),
        iOS: const DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
        ),
      ),
      payload: reportId,
    );
  }

  /// Local polling alert: Triggered when new tasks appear.
  static Future<void> notifyNewAssignments({
    required List<InspectionTask> previous,
    required List<InspectionTask> next,
  }) async {
    if (!_initialized) return;

    final prevIds = previous.map((e) => e.reportID).toSet();
    final newcomers = next.where((t) => !prevIds.contains(t.reportID)).toList();
    if (newcomers.isEmpty) return;

    for (final task in newcomers) {
      final notificationId = (task.reportID & 0x7FFFFFFF);
      await _localNotifications.show(
        notificationId,
        'New inspection assigned',
        task.detectedName,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
          ),
          iOS: const DarwinNotificationDetails(
            presentAlert: true,
            presentBadge: true,
            presentSound: true,
          ),
        ),
        payload: task.reportID.toString(),
      );
    }
  }

  /// Local polling alert: Triggered when a deadline is nearing within 24 hours.
  static Future<void> notifyApproachingDeadlines(
    List<InspectionTask> tasks,
  ) async {
    if (!_initialized) return;

    final now = DateTime.now();
    for (final task in tasks) {
      if (task.deadline == null || task.deadline!.isEmpty) continue;

      try {
        final deadline = AppDateUtils.parseToLocal(task.deadline!);
        if (deadline == null) continue;

        // Schedule exact offline background alarm for 24h & due time
        if (deadline.isAfter(now)) {
          unawaited(
            scheduleZonedDeadlineNotification(
              reportId: task.reportID,
              taskTitle: task.detectedName,
              deadline: deadline,
            ),
          );
        }

        final diff = deadline.difference(now);

        // Only alert for future deadlines within 24 hours (not already overdue)
        if (diff.inMinutes > 0 &&
            diff.inHours <= 24 &&
            !_warnedDeadlineTaskIds.contains(task.reportID)) {
          _warnedDeadlineTaskIds.add(task.reportID);

          final notificationId = ((task.reportID + 100000) & 0x7FFFFFFF);
          await _localNotifications.show(
            notificationId,
            'Approaching Deadline',
            'Task "${task.detectedName}" is due soon. Please inspect it.',
            NotificationDetails(
              android: AndroidNotificationDetails(
                _channel.id,
                _channel.name,
                channelDescription: _channel.description,
                importance: Importance.high,
                priority: Priority.high,
                icon: '@mipmap/ic_launcher',
              ),
              iOS: const DarwinNotificationDetails(
                presentAlert: true,
                presentBadge: true,
                presentSound: true,
              ),
            ),
            payload: task.reportID.toString(),
          );
        }
      } catch (e) {
        debugPrint('Error parsing deadline for task ${task.reportID}: $e');
      }
    }
  }

  /// Schedule offline exact notifications for task deadline:
  /// - 24 hours prior
  /// - Exact due date and time
  static Future<void> scheduleZonedDeadlineNotification({
    required int reportId,
    required String taskTitle,
    required DateTime deadline,
  }) async {
    if (!_initialized) return;
    final now = DateTime.now();

    // 1. 24-hour warning alert
    final warningTime = deadline.subtract(const Duration(hours: 24));
    if (warningTime.isAfter(now)) {
      final warningId = ((reportId * 10 + 1) & 0x7FFFFFFF);
      await _localNotifications.zonedSchedule(
        warningId,
        'Approaching Deadline (24 Hours Remaining)',
        'Inspection task "$taskTitle" is due tomorrow.',
        tz.TZDateTime.from(warningTime, tz.local),
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.max,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
          ),
          iOS: const DarwinNotificationDetails(
            presentAlert: true,
            presentBadge: true,
            presentSound: true,
          ),
        ),
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        payload: reportId.toString(),
      );
    }

    // 2. Exact Due Time alert
    if (deadline.isAfter(now)) {
      final dueId = ((reportId * 10 + 2) & 0x7FFFFFFF);
      await _localNotifications.zonedSchedule(
        dueId,
        'Inspection Deadline Due Now!',
        'Task "$taskTitle" is due now. Please complete and submit your report.',
        tz.TZDateTime.from(deadline, tz.local),
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.max,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
          ),
          iOS: const DarwinNotificationDetails(
            presentAlert: true,
            presentBadge: true,
            presentSound: true,
          ),
        ),
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        payload: reportId.toString(),
      );
    }
  }
}

Future<void> _initializeLocalNotifications() async {
  tz.initializeTimeZones();
  const settings = InitializationSettings(
    android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    iOS: DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    ),
  );
  await _localNotifications.initialize(
    settings,
    onDidReceiveNotificationResponse: (response) =>
        PushNotifications._scheduleAlertNavigation(response.payload),
    onDidReceiveBackgroundNotificationResponse: notificationTapBackground,
  );

  final android = _localNotifications
      .resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin
      >();
  await android?.createNotificationChannel(_channel);
}

String? _reportIdFromData(Map<String, dynamic> data) {
  final reportId = data['reportID'] ?? data['reportId'] ?? data['report_id'];
  return reportId?.toString();
}
